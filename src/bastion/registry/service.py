"""Agent records, tokens, runs and policy versions.

Classification (Assessor / Reviewer / sign-off) is added in slice S5; this module holds the
parts the gateway needs: who an agent is, which token it presents and which policy is in force.
"""

import hashlib
import secrets
import uuid

from sqlalchemy import Engine, select, update

from bastion.audit.log import AuditLog
from bastion.db import session_scope
from bastion.gateway.policy_engine import Policy, PolicyLoadError, content_hash
from bastion.models import Agent, PolicyRow, Run, iso


class RegistryError(Exception):
    pass


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Registry:
    def __init__(self, engine: Engine, audit: AuditLog | None = None) -> None:
        self.engine = engine
        self.audit = audit or AuditLog(engine)

    # --- agents and tokens -------------------------------------------------------------------
    def create_agent(
        self,
        agent_id: str,
        *,
        name: str,
        owner: str,
        tier: str | None = None,
        status: str = "draft",
        actor: str = "system",
    ) -> Agent:
        with session_scope(self.engine) as session:
            if session.get(Agent, agent_id):
                raise RegistryError(f"agent '{agent_id}' already exists")
            agent = Agent(id=agent_id, name=name, owner=owner, tier=tier, status=status)
            session.add(agent)
        self.audit.append(
            "agent_registered",
            actor=actor,
            agent_id=agent_id,
            payload={"name": name, "owner": owner, "tier": tier, "status": status},
        )
        return agent

    def get_agent(self, agent_id: str) -> Agent | None:
        with session_scope(self.engine) as session:
            return session.get(Agent, agent_id)

    def list_agents(self) -> list[Agent]:
        with session_scope(self.engine) as session:
            return list(session.scalars(select(Agent).order_by(Agent.id)))

    def issue_token(self, agent_id: str, *, actor: str = "system") -> str:
        """Issue (or rotate) the agent's gateway token. Returned once; only its hash is stored."""
        token = secrets.token_urlsafe(32)
        with session_scope(self.engine) as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                raise RegistryError(f"unknown agent '{agent_id}'")
            if agent.status != "active":
                raise RegistryError(
                    f"agent '{agent_id}' is {agent.status}; no token before sign-off"
                )
            agent.token_hash = hash_token(token)
        self.audit.append("token_issued", actor=actor, agent_id=agent_id)
        return token

    def authenticate(self, token: str | None) -> str | None:
        """Return the agent id for a valid token of an agent that may connect, else None.

        A killed agent still authenticates so that its calls are denied *and recorded* by the
        kill switch rather than disappearing as anonymous 401s.
        """
        if not token:
            return None
        with session_scope(self.engine) as session:
            agent = session.scalar(select(Agent).where(Agent.token_hash == hash_token(token)))
            if agent is None or agent.status not in ("active", "killed"):
                return None
            return agent.id

    # --- runs --------------------------------------------------------------------------------
    def start_run(self, agent_id: str, scenario: str | None = None) -> str:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        with session_scope(self.engine) as session:
            session.add(Run(id=run_id, agent_id=agent_id, scenario=scenario, thread_id=run_id))
        self.audit.append(
            "run_started",
            actor=agent_id,
            agent_id=agent_id,
            payload={"run_id": run_id, "scenario": scenario},
        )
        return run_id

    def set_run_status(self, run_id: str, status: str) -> None:
        ended = iso() if status in ("completed", "halted", "failed") else None
        with session_scope(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise RegistryError(f"unknown run '{run_id}'")
            run.status, run.ended_at = status, ended
            agent_id = run.agent_id
        self.audit.append(
            "run_status",
            actor="system",
            agent_id=agent_id,
            payload={"run_id": run_id, "status": status},
        )

    def resolve_run(self, agent_id: str, run_id: str | None) -> str:
        """Map a client-supplied run id to a budget bucket.

        Only runs that Bastion itself started for this agent count as sessions. Anything else
        falls into one shared bucket per agent, so inventing run ids cannot reset a budget.
        """
        if run_id:
            with session_scope(self.engine) as session:
                run = session.get(Run, run_id)
                if run is not None and run.agent_id == agent_id:
                    return run_id
        return "unbound"


class PolicyStore:
    def __init__(self, engine: Engine, audit: AuditLog | None = None) -> None:
        self.engine = engine
        self.audit = audit or AuditLog(engine)
        self._cache: dict[str, Policy] = {}

    def activate(self, agent_id: str, yaml_text: str, *, created_by: str) -> PolicyRow:
        """Validate, store as a new version and make it the policy in force (FR-15)."""
        policy = Policy.from_yaml(yaml_text)  # raises PolicyLoadError; nothing is stored
        if policy.agent != agent_id:
            raise PolicyLoadError(f"policy is for agent '{policy.agent}', not '{agent_id}'")
        with session_scope(self.engine) as session:
            versions = session.scalars(
                select(PolicyRow.version).where(PolicyRow.agent_id == agent_id)
            ).all()
            previous = session.scalar(
                select(PolicyRow.content_hash).where(
                    PolicyRow.agent_id == agent_id, PolicyRow.active.is_(True)
                )
            )
            session.execute(
                update(PolicyRow).where(PolicyRow.agent_id == agent_id).values(active=False)
            )
            row = PolicyRow(
                agent_id=agent_id,
                version=max(versions, default=0) + 1,
                content_yaml=yaml_text,
                content_hash=policy.content_hash,
                active=True,
                created_by=created_by,
            )
            session.add(row)
        self.audit.append(
            "policy_activated",
            actor=created_by,
            agent_id=agent_id,
            payload={
                "version": row.version,
                "policy_hash": row.content_hash,
                "previous_hash": previous,
                "note": policy.version_note,
            },
        )
        return row

    def active_row(self, agent_id: str) -> PolicyRow | None:
        with session_scope(self.engine) as session:
            return session.scalar(
                select(PolicyRow).where(PolicyRow.agent_id == agent_id, PolicyRow.active.is_(True))
            )

    def active(self, agent_id: str) -> Policy | None:
        """The policy in force, parsed. Raises PolicyLoadError if the stored text is invalid."""
        row = self.active_row(agent_id)
        if row is None:
            return None
        if content_hash(row.content_yaml) != row.content_hash:
            raise PolicyLoadError("stored policy does not match its recorded hash")
        if row.content_hash not in self._cache:
            self._cache[row.content_hash] = Policy.from_yaml(row.content_yaml)
        return self._cache[row.content_hash]

    def versions(self, agent_id: str) -> list[PolicyRow]:
        with session_scope(self.engine) as session:
            return list(
                session.scalars(
                    select(PolicyRow)
                    .where(PolicyRow.agent_id == agent_id)
                    .order_by(PolicyRow.version.desc())
                )
            )
