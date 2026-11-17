"""The requirements documents stay tied to the code (R1).

Every test they cite must exist, every eval scenario id must exist, and every "Roadmap" label
must carry a phase, so a reader can never mistake a plan for a feature.
"""

import re

import pytest

from bastion.config import REPO_ROOT

DOCS = REPO_ROOT / "docs" / "requirements"
NAMES = ["FRD-AI-Native.md", "FRD-Enterprise.md", "Bastion-Requirements-Brief.md"]
# A phase straight after the word, or a generic use of the word: a heading, the glossary entry,
# a sentence explaining the labelling convention.
PHASED = re.compile(
    r"Roadmap(,? P[123]\b|,? \(?no phase( assigned)?\)?|\s*\(P[123]\b|\*\*,? with"
    r"| with (its|the|their) phase| criteria| requirements| rows| items|:|$)"
)


def defined_tests() -> set[tuple[str, str]]:
    found = set()
    for path in (REPO_ROOT / "tests").glob("test_*.py"):
        for name in re.findall(r"^(?:async )?def (test_\w+)", path.read_text(), re.M):
            found.add((path.name, name))
    return found


@pytest.mark.parametrize("name", NAMES)
def test_cited_tests_exist(name):
    text = (DOCS / name).read_text(encoding="utf-8")
    cited = set(re.findall(r"(test_\w+\.py)::(test_\w+)", text))
    missing = sorted(cited - defined_tests())
    assert not missing, missing


@pytest.mark.parametrize("name", NAMES)
def test_cited_eval_scenarios_exist(name):
    text = (DOCS / name).read_text(encoding="utf-8")
    for prefix, folder in (("RT", "redteam"), ("B", "benign")):
        for number in set(re.findall(rf"\b{prefix}-(\d\d)\b", text)):
            assert (REPO_ROOT / "evals" / folder / f"{prefix}-{number}.yaml").is_file(), (
                f"{prefix}-{number}"
            )


@pytest.mark.parametrize("name", NAMES)
def test_every_roadmap_label_has_a_phase(name):
    text = (DOCS / name).read_text(encoding="utf-8")
    bare = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in re.finditer(r"\bRoadmap\b", line):
            tail = line[match.start() :]
            glossary = line.startswith("| Roadmap |")
            if not glossary and not PHASED.match(tail):
                bare.append(f"{name}:{number}: {line.strip()[:120]}")
    assert not bare, bare


def test_exports_exist_for_every_document():
    for name in NAMES:
        stem = name.removesuffix(".md")
        for suffix in (".docx", ".pdf"):
            assert (DOCS / "exports" / f"{stem}{suffix}").stat().st_size > 10_000, stem + suffix
