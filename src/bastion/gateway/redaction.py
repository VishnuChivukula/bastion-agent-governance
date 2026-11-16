"""PII detection and masking (FR-14).

Two engines find the same four entity types and share all masking logic:

- `Redactor`: Microsoft Presidio, configured explicitly with spaCy `en_core_web_sm`. The default.
- `LightRedactor`: a small built-in pattern engine (regular expressions, checksums and the
  `phonenumbers` library) for low-memory deployments (`BASTION_LOW_MEMORY=true`). It avoids
  loading Presidio and spaCy, which cost about 150 MB. See ADR-010 for what that trades away.

Either is expensive enough to build once and share per process (`get_redactor`).
"""

import re
from functools import lru_cache
from typing import Any

SUPPORTED_ENTITIES = ("EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD")
MIN_SCORE = 0.35

# Presidio's e-mail recogniser checks the TLD against the public suffix list, so it misses
# reserved test domains such as `user@bank.example`. This pattern covers them.
EMAIL_ANY_TLD = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b"

Span = tuple[int, int, str]


def resolve_overlaps(scored: list[tuple[float, int, int, str]]) -> list[Span]:
    """Non-overlapping spans: the highest score wins, then the earliest start."""
    spans: list[Span] = []
    for _, start, end, entity in sorted(scored, key=lambda r: (-r[0], r[1])):
        if all(end <= s or start >= e for s, e, _ in spans):
            spans.append((start, end, entity))
    return sorted(spans)


class BaseRedactor:
    engine = "base"

    def find(self, text: str, entities: list[str]) -> list[Span]:
        """Non-overlapping (start, end, entity_type) spans."""
        raise NotImplementedError

    def redact_text(self, text: str, entities: list[str]) -> tuple[str, dict[str, int]]:
        counts: dict[str, int] = {}
        out = text
        for start, end, entity in reversed(self.find(text, entities)):
            out = f"{out[:start]}<{entity}>{out[end:]}"
            counts[entity] = counts.get(entity, 0) + 1
        return out, counts

    def redact(self, value: Any, entities: list[str]) -> tuple[Any, dict[str, int]]:
        """Mask PII in every string inside a JSON-like value. Returns (masked, counts)."""
        counts: dict[str, int] = {}
        if not entities:
            return value, counts

        def walk(node: Any) -> Any:
            if isinstance(node, str):
                masked, found = self.redact_text(node, entities)
                for entity, n in found.items():
                    counts[entity] = counts.get(entity, 0) + n
                return masked
            if isinstance(node, list):
                return [walk(item) for item in node]
            if isinstance(node, dict):
                return {key: walk(item) for key, item in node.items()}
            return node

        return walk(value), counts

    def scan(self, value: Any, entities: list[str]) -> dict[str, int]:
        """Count PII entities in a JSON-like value without changing it (DLP on tool inputs)."""
        return self.redact(value, entities)[1]


class Redactor(BaseRedactor):
    """Presidio with spaCy. Imported lazily: a low-memory process never loads either."""

    engine = "presidio"

    def __init__(self) -> None:
        from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }
        ).create_engine()
        # Every entity Bastion supports is found by pattern and checksum recognisers, so the
        # statistical parser and NER stages are switched off: they dominated gateway latency.
        pipeline = nlp_engine.nlp["en"]
        for stage in ("parser", "ner"):
            if stage in pipeline.pipe_names:
                pipeline.disable_pipe(stage)
        self._analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
        self._analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="EMAIL_ADDRESS",
                name="EmailAnyTldRecognizer",
                patterns=[Pattern("email_any_tld", EMAIL_ANY_TLD, 0.9)],
            )
        )
        self.find("warm-up a@example.com", list(SUPPORTED_ENTITIES))

    def find(self, text: str, entities: list[str]) -> list[Span]:
        results = self._analyzer.analyze(
            text=text, entities=entities, language="en", score_threshold=MIN_SCORE
        )
        return resolve_overlaps([(r.score, r.start, r.end, r.entity_type) for r in results])


_EMAIL = re.compile(EMAIL_ANY_TLD)
# Card-like digit groups; kept only if the Luhn checksum holds.
_CARD = re.compile(
    r"\b(?!1\d{12}(?!\d))(?:4\d{3}|5[0-5]\d{2}|6\d{3}|1\d{3}|3\d{3})"
    r"[- ]?\d{3,4}[- ]?\d{3,4}[- ]?\d{3,5}\b"
)
# IBAN-like: country, two check digits, then 11 to 30 characters, optionally in groups.
_IBAN = re.compile(r"\b[A-Za-z]{2}\d{2}(?:[ ]?[A-Za-z0-9]){11,30}\b")
_PHONE_REGIONS = ("US", "GB", "DE", "FR", "IL", "IN", "CA", "BR")


# IBAN length by country (ISO 13616 registry), for the countries this demo is likely to meet.
IBAN_LENGTHS = {
    "AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "EE": 20,
    "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GR": 27, "HR": 21, "HU": 28, "IE": 22, "IS": 26,
    "IT": 27, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MT": 31, "NL": 18, "NO": 15, "PL": 28,
    "PT": 25, "RO": 24, "SE": 24, "SI": 19, "SK": 24,
}  # fmt: skip


def luhn_valid(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def iban_valid(candidate: str) -> bool:
    """ISO 13616 mod-97 check on a compact (no spaces) candidate."""
    if not 15 <= len(candidate) <= 34:
        return False
    rearranged = candidate[4:] + candidate[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97 == 1


class LightRedactor(BaseRedactor):
    """Pattern engine for low-memory deployments: the same four entity types, no NLP model."""

    engine = "light"

    def __init__(self) -> None:
        import phonenumbers

        self._phonenumbers = phonenumbers

    def _ibans(self, text: str) -> list[tuple[float, int, int, str]]:
        found = []
        for match in _IBAN.finditer(text):
            # The pattern can run on into following words or digits. Shorten the candidate
            # from the right until it is a well-formed IBAN that ends at a word boundary.
            raw = match.group()
            expected = IBAN_LENGTHS.get(raw[:2].upper())
            for end in range(len(raw), 14, -1):
                piece = raw[:end]
                following = text[match.start() + end : match.start() + end + 1]
                if piece.endswith(" ") or following.isalnum():
                    continue
                compact = piece.replace(" ", "").upper()
                if expected is not None and len(compact) != expected:
                    continue  # a chance checksum match of the wrong length is not an IBAN
                if expected is None and end != len(raw):
                    continue  # unknown country: accept only the whole candidate
                if iban_valid(compact):
                    found.append((1.0, match.start(), match.start() + end, "IBAN_CODE"))
                    break
        return found

    def _phones(self, text: str) -> list[tuple[float, int, int, str]]:
        spans = set()
        for region in _PHONE_REGIONS:
            matcher = self._phonenumbers.PhoneNumberMatcher(
                text, region, leniency=self._phonenumbers.Leniency.VALID
            )
            spans.update((match.start, match.end) for match in matcher)
        return [(0.4, start, end, "PHONE_NUMBER") for start, end in sorted(spans)]

    def find(self, text: str, entities: list[str]) -> list[Span]:
        scored: list[tuple[float, int, int, str]] = []
        if "EMAIL_ADDRESS" in entities:
            scored += [(1.0, m.start(), m.end(), "EMAIL_ADDRESS") for m in _EMAIL.finditer(text)]
        if "IBAN_CODE" in entities:
            scored += self._ibans(text)
        if "CREDIT_CARD" in entities:
            scored += [
                (1.0, m.start(), m.end(), "CREDIT_CARD")
                for m in _CARD.finditer(text)
                if luhn_valid(re.sub(r"[- ]", "", m.group()))
            ]
        if "PHONE_NUMBER" in entities:
            scored += self._phones(text)
        return resolve_overlaps(scored)


@lru_cache(maxsize=2)
def _build(low_memory: bool) -> BaseRedactor:
    return LightRedactor() if low_memory else Redactor()


def get_redactor(low_memory: bool | None = None) -> BaseRedactor:
    """The process-wide PII engine: Presidio, or the pattern engine in low-memory mode.
    `low_memory=None` reads the setting from the environment."""
    if low_memory is None:
        from bastion.config import get_settings

        low_memory = get_settings().low_memory
    return _build(bool(low_memory))
