"""Pydantic v2 schema models for Arena scenarios and trials.

A `Scenario` is a themed setting an agent is dropped into for a match (e.g.
`github-maintainer-dungeon`). A `Trial` is a single, individually scored
situation within a scenario — a specific action or attempt an agent will
make or be prompted toward, along with the decision agent-assembly's
victory/defeat model is expected to render for it.

These models describe the schema only. Resolving a `ScenarioSpec`'s trial-id
references into loaded `TrialSpec` instances, and reading either from YAML,
is handled by the loader in `arena.scenarios.loader`.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Kebab-case identifier: lowercase alphanumerics, hyphen-separated segments.
# Matches the id style used in the AAASM-4368 scenario/trial examples
# (e.g. "github-maintainer-dungeon", "prompt-injection-code-write").
_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_id(value: str) -> str:
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"{value!r} is not a valid id — expected lowercase kebab-case "
            "(e.g. 'github-maintainer-dungeon')"
        )
    return value


class Decision(str, Enum):
    """The governance verdict agent-assembly can render for an agent action.

    Decisions always come from agent-assembly; Arena only records what a
    trial *expects* the decision to be and compares it to what actually
    happened.
    """

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    REDACT = "redact"
    DROP = "drop"
    QUARANTINE = "quarantine"


class Severity(str, Enum):
    """Expected criticality of a trial if agent-assembly gets it wrong.

    `CRITICAL` marks a trial whose failure counts as a "critical escape" —
    the headline failure mode that alone is enough to score a match as a
    defeat.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TrialSpec(BaseModel):
    """A single scored situation within a scenario.

    `expected` maps an action/resource identifier (e.g.
    `"github.contents.write"`) to the `Decision` agent-assembly is expected
    to render for it. A trial passes when every actual decision matches its
    expected decision, with complete audit evidence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    description: str = Field(min_length=1)
    agent_roles: list[str] = Field(default_factory=list)
    expected: dict[str, Decision] = Field(min_length=1)
    severity: Severity
    #: Optional (AAASM-4404): when set, this trial expects the agent to run
    #: under the named `BehaviorProfile` (`arena.models.manifest`) rather
    #: than whichever mode it defaults to. `None` (the default) means "no
    #: behavior-profile distinction" — every trial written before this
    #: subtask, and any scenario that doesn't care about behavior profiles,
    #: stays valid unchanged. Cross-referential validation — that a set
    #: `behavior_id` is actually declared by an agent compatible with this
    #: trial's scenario — is not this model's job; see
    #: `arena.scenarios.loader.validate_trial_behaviors`.
    behavior_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id_is_kebab_case(cls, value: str) -> str:
        return _validate_id(value)

    @field_validator("behavior_id")
    @classmethod
    def _behavior_id_is_kebab_case_if_set(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_id(value)

    @field_validator("expected")
    @classmethod
    def _expected_keys_are_non_empty(cls, value: dict[str, Decision]) -> dict[str, Decision]:
        for key in value:
            if not key.strip():
                raise ValueError("expected decision keys must be non-empty strings")
        return value

    @property
    def is_critical_escape(self) -> bool:
        """Whether an unexpected decision on this trial is a critical escape."""
        return self.severity is Severity.CRITICAL


class VictoryConditions(BaseModel):
    """Machine-readable thresholds a scenario must stay under to be a win.

    All three default to zero, mirroring the Epic's victory definition:
    zero critical escapes, zero unexpected allows, zero secret exposures.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    critical_escapes: int = Field(default=0, ge=0)
    unexpected_allows: int = Field(default=0, ge=0)
    secret_exposures: int = Field(default=0, ge=0)


class ScenarioSpec(BaseModel):
    """A themed setting an agent is dropped into for a match.

    `trials` holds the ids of the `TrialSpec`s that make up this scenario —
    resolving those ids into loaded trial instances (and validating that
    every referenced trial actually exists) is the loader's job, not this
    model's.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    victory_conditions: VictoryConditions = Field(default_factory=VictoryConditions)
    trials: list[str] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _id_is_kebab_case(cls, value: str) -> str:
        return _validate_id(value)

    @field_validator("trials")
    @classmethod
    def _trial_ids_are_valid_and_unique(cls, value: list[str]) -> list[str]:
        for trial_id in value:
            _validate_id(trial_id)
        if len(set(value)) != len(value):
            raise ValueError(f"duplicate trial ids in scenario.trials: {value!r}")
        return value
