"""Agent card and classification models (FR-01..FR-03)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Tier = Literal["prohibited", "high", "limited", "minimal"]
TIERS: tuple[str, ...] = ("prohibited", "high", "limited", "minimal")
Autonomy = Literal["suggest", "act_with_approval", "autonomous"]
# "global" is the kill switch scope for all agents; "unbound" is the shared budget bucket.
RESERVED_IDS = frozenset({"global", "unbound"})


class AgentCard(BaseModel):
    """What an owner declares about an agent before it may act (FR-01)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")

    @field_validator("id")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        if value in RESERVED_IDS:
            raise ValueError(f"'{value}' is a reserved name and cannot be an agent id")
        return value

    name: str = Field(min_length=1, max_length=120)
    owner: str = Field(min_length=1, max_length=200)
    business_purpose: str = Field(min_length=10, max_length=2000)
    deployment_context: str = Field(min_length=1, max_length=2000)
    affected_users: str = Field(min_length=1, max_length=1000)
    data_categories: list[str] = Field(default_factory=list, max_length=30)
    personal_data: bool = False
    special_category_data: bool = False
    tools_requested: list[str] = Field(default_factory=list, max_length=50)
    autonomy_level: Autonomy
    models_used: list[str] = Field(default_factory=list, max_length=10)


class Assessment(BaseModel):
    """The Assessor's structured proposal (FR-02)."""

    model_config = ConfigDict(extra="forbid")

    tier: Tier
    rationale: str
    cited_provisions: list[str]  # each carries [VERIFY]
    likely_obligations: list[str]
    confidence: float = Field(ge=0, le=1)
    open_questions: list[str]


class Review(BaseModel):
    """The Reviewer's independent critique (FR-03)."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["agree", "disagree"]
    recommended_tier: Tier
    challenges: list[str]
    summary: str


class Classification(BaseModel):
    """Everything the human sees before sign-off."""

    assessment: Assessment
    review: Review
    revised: Assessment | None = None  # set when the Reviewer disagreed (one revision only)

    @property
    def proposed(self) -> Assessment:
        return self.revised or self.assessment

    @property
    def unresolved_disagreement(self) -> bool:
        """True when, after the single allowed revision, the two agents still differ."""
        return self.review.verdict == "disagree" and (
            self.proposed.tier != self.review.recommended_tier
        )


def _schema(model: type[BaseModel]) -> dict:
    """JSON schema for structured output: closed objects, every field required, no bounds
    (numeric bounds are checked by Pydantic after the call)."""
    schema = model.model_json_schema()
    schema.pop("title", None)
    for prop in schema["properties"].values():
        prop.pop("title", None)
        prop.pop("minimum", None)
        prop.pop("maximum", None)
    schema["required"] = list(schema["properties"])
    schema["additionalProperties"] = False
    return schema


ASSESSMENT_SCHEMA = _schema(Assessment)
REVIEW_SCHEMA = _schema(Review)
