"""Unit tests for `ArenaActionAttempt` (AAASM-4379): required fields,
`extra="forbid"`/frozen behavior, and JSON round-trip."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.integrations.models import ArenaActionAttempt

_REQUIRED_FIELDS: dict[str, object] = {
    "agent_id": "raw-python-issue-triager",
    "framework": "raw-python",
    "scenario_id": "github-maintainer-dungeon",
    "trial_id": "prompt-injection-code-write",
    "tool": "github.contents.write",
    "resource": "src/app.py",
}


def test_construct_with_required_fields_only() -> None:
    attempt = ArenaActionAttempt(**_REQUIRED_FIELDS)  # type: ignore[arg-type]

    assert attempt.agent_id == "raw-python-issue-triager"
    assert attempt.framework == "raw-python"
    assert attempt.scenario_id == "github-maintainer-dungeon"
    assert attempt.trial_id == "prompt-injection-code-write"
    assert attempt.tool == "github.contents.write"
    assert attempt.resource == "src/app.py"
    # Defaults: empty args, no context, a timestamp was auto-assigned.
    assert attempt.args == {}
    assert attempt.context is None
    assert attempt.timestamp is not None


@pytest.mark.parametrize(
    "missing_field", ["agent_id", "framework", "scenario_id", "trial_id", "tool", "resource"]
)
def test_missing_required_field_raises(missing_field: str) -> None:
    fields = dict(_REQUIRED_FIELDS)
    del fields[missing_field]

    with pytest.raises(ValidationError):
        ArenaActionAttempt(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "blank_field", ["agent_id", "framework", "scenario_id", "trial_id", "tool", "resource"]
)
def test_blank_required_field_raises(blank_field: str) -> None:
    fields = dict(_REQUIRED_FIELDS)
    fields[blank_field] = ""

    with pytest.raises(ValidationError):
        ArenaActionAttempt(**fields)  # type: ignore[arg-type]


def test_unknown_field_is_rejected() -> None:
    fields = {**_REQUIRED_FIELDS, "unexpected": "nope"}

    with pytest.raises(ValidationError):
        ArenaActionAttempt(**fields)  # type: ignore[arg-type]


def test_instance_is_frozen() -> None:
    attempt = ArenaActionAttempt(**_REQUIRED_FIELDS)  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        attempt.tool = "something.else"  # type: ignore[misc]


def test_json_round_trip_preserves_all_fields() -> None:
    original = ArenaActionAttempt(
        **_REQUIRED_FIELDS,  # type: ignore[arg-type]
        args={"branch": "main", "message": "apply fix"},
        context="Naive triage: complying with an injected instruction.",
    )

    payload = original.model_dump_json()
    restored = ArenaActionAttempt.model_validate_json(payload)

    assert restored == original
    assert restored.args == {"branch": "main", "message": "apply fix"}
    assert restored.context == "Naive triage: complying with an injected instruction."


def test_json_round_trip_via_model_dump_and_validate() -> None:
    original = ArenaActionAttempt(**_REQUIRED_FIELDS)  # type: ignore[arg-type]

    dumped = original.model_dump(mode="json")
    restored = ArenaActionAttempt.model_validate(dumped)

    assert restored == original
