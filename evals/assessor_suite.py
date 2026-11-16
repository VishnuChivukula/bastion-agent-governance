"""Suite C: assessor accuracy on 12 synthetic agent cards (docs/EVALS.md).

Runs the real Assessor → Reviewer → revise graph for every card, then asks the Reviewer to
judge three deliberately wrong assessments. In replay mode (the default, and what CI uses) the
model answers come from fixtures; `make record` runs this in record mode to refresh them.

    python -m evals.assessor_suite          # prints the scoreboard
"""

import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from bastion.config import REPO_ROOT, Settings, get_settings
from bastion.db import make_engine
from bastion.registry.assessor_graph import AssessmentError, load_knowledge, review
from bastion.registry.classification import ClassificationService, sample_cards
from bastion.registry.models import Assessment

SUITE_DIR = REPO_ROOT / "evals" / "assessor"


def run(settings: Settings | None = None, transport: Any = None) -> dict[str, Any]:
    settings = settings or get_settings()
    gold = yaml.safe_load((SUITE_DIR / "gold.yaml").read_text(encoding="utf-8"))["gold"]
    seeded = yaml.safe_load((SUITE_DIR / "seeded_errors.yaml").read_text(encoding="utf-8"))
    cards = {card.id: card for card in sample_cards()}
    cases: list[dict[str, Any]] = []
    catches: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="bastion-assessor-") as tmp:
        engine = make_engine(Path(tmp) / "bastion.db")
        service = ClassificationService(engine, settings=settings, transport=transport)
        deps = service.deps()
        knowledge = load_knowledge()
        for card in cards.values():
            case: dict[str, Any] = {
                "suite": "assessor", "id": card.id, "expected": "|".join(gold[card.id]),
            }  # fmt: skip
            try:
                result = service.register(card, actor="eval")
            except AssessmentError as exc:
                case.update(actual=f"invalid output: {exc}"[:200], valid=False, **{"pass": False})
            else:
                tier = result.proposed.tier
                case.update(
                    actual=tier,
                    valid=True,
                    assessor_tier=result.assessment.tier,
                    reviewer_verdict=result.review.verdict,
                    revised=result.revised is not None,
                    confidence=result.proposed.confidence,
                    verify_marked=all("[VERIFY]" in p for p in result.proposed.cited_provisions),
                    **{"pass": tier in gold[card.id]},
                )
            cases.append(case)
        for item in seeded["seeded_errors"]:
            wrong = Assessment(
                tier=item["wrong_tier"],
                rationale=item["wrong_rationale"],
                cited_provisions=[],
                likely_obligations=[],
                confidence=0.9,
                open_questions=[],
            )
            entry = {"suite": "assessor-reviewer", "id": item["id"], "expected": "disagree"}
            try:
                critique = review(deps, cards[item["card"]], knowledge, wrong)
            except AssessmentError as exc:
                entry.update(actual=f"invalid output: {exc}"[:200], valid=False, **{"pass": False})
            else:
                caught = critique.verdict == "disagree" and (
                    critique.recommended_tier in gold[item["card"]]
                )
                entry.update(
                    actual=f"{critique.verdict} → {critique.recommended_tier}",
                    valid=True,
                    **{"pass": caught},
                )
            catches.append(entry)
        engine.dispose()
    everything = cases + catches
    return {
        "cases": everything,
        "tier_accuracy": sum(c["pass"] for c in cases) / len(cases),
        "reviewer_catches": sum(c["pass"] for c in catches),
        "reviewer_seeded": len(catches),
        "structured_validity": sum(c["valid"] for c in everything) / len(everything),
        "verify_marked": all(c.get("verify_marked", True) for c in cases),
    }


def main() -> int:
    result = run()
    for case in result["cases"]:
        mark = "PASS" if case["pass"] else "FAIL"
        print(f"{mark}  {case['id']:<36} expected {case['expected']:<14} got {case['actual']}")
    print(
        f"\ntier accuracy {result['tier_accuracy']:.0%} · reviewer caught "
        f"{result['reviewer_catches']}/{result['reviewer_seeded']} seeded errors · "
        f"structured output validity {result['structured_validity']:.0%}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
