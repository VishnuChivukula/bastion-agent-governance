"""PII detection and masking with Microsoft Presidio (FR-14).

The analyzer is configured explicitly with spaCy `en_core_web_sm`. It is expensive to build, so
one instance is shared per process (`get_redactor`).
"""

from functools import lru_cache
from typing import Any

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider

SUPPORTED_ENTITIES = ("EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD")
MIN_SCORE = 0.35

# Presidio's e-mail recogniser checks the TLD against the public suffix list, so it misses
# reserved test domains such as `user@bank.example`. This pattern covers them.
_EMAIL_ANY_TLD = PatternRecognizer(
    supported_entity="EMAIL_ADDRESS",
    name="EmailAnyTldRecognizer",
    patterns=[
        Pattern(
            "email_any_tld",
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b",
            0.9,
        )
    ],
)


class Redactor:
    def __init__(self) -> None:
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
        self._analyzer.registry.add_recognizer(_EMAIL_ANY_TLD)
        self.find("warm-up a@example.com", list(SUPPORTED_ENTITIES))

    def find(self, text: str, entities: list[str]) -> list[tuple[int, int, str]]:
        """Non-overlapping (start, end, entity_type) spans, highest score first on overlap."""
        results = self._analyzer.analyze(
            text=text, entities=entities, language="en", score_threshold=MIN_SCORE
        )
        spans: list[tuple[int, int, str]] = []
        for result in sorted(results, key=lambda r: (-r.score, r.start)):
            if all(result.end <= s or result.start >= e for s, e, _ in spans):
                spans.append((result.start, result.end, result.entity_type))
        return sorted(spans)

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


@lru_cache(maxsize=1)
def get_redactor() -> Redactor:
    return Redactor()
