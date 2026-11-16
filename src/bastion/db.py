"""SQLite (WAL) engine and session helpers (ADR-005)."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from bastion.models import Base


def make_engine(db_path: Path | str) -> Engine:
    """Create the engine, enable WAL and create tables.

    Transactions are driven explicitly (the sqlite3 driver's implicit BEGIN is disabled) so a
    connection opened with `execution_options(immediate=True)` takes the write lock up front.
    The audit log relies on that to serialise appends to the hash chain.
    """
    path = Path(db_path)
    if str(db_path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 15}
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):  # pragma: no cover - driver plumbing
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        immediate = conn.get_execution_options().get("immediate", False)
        conn.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

    Base.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """A unit of work. It takes the SQLite write lock when it begins (BEGIN IMMEDIATE).

    Most units of work here read and then write. A deferred transaction that does that fails
    with "database is locked" if another connection commits in between, and SQLite's busy
    timeout does not apply to that upgrade. Taking the lock up front makes writers queue
    (up to the 15 s timeout) instead of failing. Plain reads use `engine.connect()`.
    """
    session = Session(engine.execution_options(immediate=True), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
