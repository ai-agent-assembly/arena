"""Unit tests for `DefenseDecision` (AAASM-4378): required fields,
`extra="forbid"`/frozen behavior, and field preservation across every
`Decision` value."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.integrations.decision import DefenseDecision
from arena.models.scenario import Decision, Severity

_REQUIRED_FIELDS: dict[str, object] = {
    "effect": Decision.DENY,
    "layer": "policy",
    "reason": "matched rule blocking secret exfiltration",
    "severity": Severity.CRITICAL,
}


def test_construct_with_required_fields_only() -> None:
    decision = DefenseDecision(**_REQUIRED_FIELDS)  # type: ignore[arg-type]

    assert decision.effect is Decision.DENY
    assert decision.layer == "policy"
    assert decision.reason == "matched rule blocking secret exfiltration"
    assert decision.severity is Severity.CRITICAL
    # Defaults: no policy_id, empty obligations.
    assert decision.policy_id is None
    assert decision.obligations == []


@pytest.mark.parametrize("missing_field", ["effect", "layer", "reason", "severity"])
def test_missing_required_field_raises(missing_field: str) -> None:
    fields = dict(_REQUIRED_FIELDS)
    del fields[missing_field]

    with pytest.raises(ValidationError):
        DefenseDecision(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("blank_field", ["layer", "reason"])
def test_blank_required_string_field_raises(blank_field: str) -> None:
    fields = dict(_REQUIRED_FIELDS)
    fields[blank_field] = ""

    with pytest.raises(ValidationError):
        DefenseDecision(**fields)  # type: ignore[arg-type]


def test_unknown_field_is_rejected() -> None:
    fields = {**_REQUIRED_FIELDS, "unexpected": "nope"}

    with pytest.raises(ValidationError):
        DefenseDecision(**fields)  # type: ignore[arg-type]


def test_instance_is_frozen() -> None:
    decision = DefenseDecision(**_REQUIRED_FIELDS)  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        decision.effect = Decision.ALLOW  # type: ignore[misc]


@pytest.mark.parametrize("effect", list(Decision))
def test_every_decision_value_round_trips(effect: Decision) -> None:
    original = DefenseDecision(
        effect=effect,
        layer="policy",
        reason=f"canned decision for {effect.value}",
        policy_id="policy-42",
        severity=Severity.MEDIUM,
        obligations=["redact ssn field"],
    )

    payload = original.model_dump_json()
    restored = DefenseDecision.model_validate_json(payload)

    assert restored == original
    assert restored.effect is effect
    assert restored.policy_id == "policy-42"
    assert restored.obligations == ["redact ssn field"]
