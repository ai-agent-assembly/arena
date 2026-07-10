"""Unit tests for `AgentAssemblyClient`/`FakeAgentAssemblyClient`
(AAASM-4378): decision round-tripping for every `Decision` value, the
missing-decision failure path, building a fake client from a real
`TrialSpec.expected` mapping, and the fake-vs-real adapter choice mechanism.
"""

from __future__ import annotations

import pytest

from arena.integrations.adapter import (
    AdapterChoice,
    AgentAssemblyClient,
    FakeAgentAssemblyClient,
    MissingDecisionError,
    build_agent_assembly_client,
)
from arena.integrations.decision import DefenseDecision
from arena.integrations.models import ArenaActionAttempt
from arena.models.scenario import Decision, Severity, TrialSpec

_ALL_DECISIONS = list(Decision)


def _attempt(
    *, trial_id: str = "trial-a", tool: str = "github.contents.write"
) -> ArenaActionAttempt:
    return ArenaActionAttempt(
        agent_id="agent-a",
        framework="raw-python",
        scenario_id="github-maintainer-dungeon",
        trial_id=trial_id,
        tool=tool,
        resource="src/app.py",
    )


def test_fake_client_satisfies_agent_assembly_client_protocol() -> None:
    client: AgentAssemblyClient = FakeAgentAssemblyClient()
    assert isinstance(client, AgentAssemblyClient)


@pytest.mark.parametrize("effect", _ALL_DECISIONS)
def test_fake_client_returns_configured_decision_preserving_all_fields(effect: Decision) -> None:
    attempt = _attempt()
    decision = DefenseDecision(
        effect=effect,
        layer="policy",
        reason=f"canned decision for {effect.value}",
        policy_id="policy-42",
        severity=Severity.HIGH,
        obligations=["redact ssn field"],
    )
    client = FakeAgentAssemblyClient(decisions={(attempt.trial_id, attempt.tool): decision})

    result = client.decide(attempt)

    assert result == decision
    assert result.effect is effect
    assert result.layer == "policy"
    assert result.reason == f"canned decision for {effect.value}"
    assert result.policy_id == "policy-42"
    assert result.severity is Severity.HIGH
    assert result.obligations == ["redact ssn field"]


def test_fake_client_keys_decisions_by_trial_id_and_tool() -> None:
    deny = DefenseDecision(
        effect=Decision.DENY, layer="policy", reason="deny", severity=Severity.LOW
    )
    allow = DefenseDecision(
        effect=Decision.ALLOW, layer="policy", reason="allow", severity=Severity.LOW
    )
    client = FakeAgentAssemblyClient(
        decisions={
            ("trial-a", "tool.x"): deny,
            ("trial-b", "tool.x"): allow,
        }
    )

    assert client.decide(_attempt(trial_id="trial-a", tool="tool.x")).effect is Decision.DENY
    assert client.decide(_attempt(trial_id="trial-b", tool="tool.x")).effect is Decision.ALLOW


def test_fake_client_raises_missing_decision_error_when_unconfigured() -> None:
    client = FakeAgentAssemblyClient()

    with pytest.raises(MissingDecisionError) as exc_info:
        client.decide(_attempt())

    assert "trial-a" in str(exc_info.value)
    assert "github.contents.write" in str(exc_info.value)


def test_fake_client_default_construction_has_no_configured_decisions() -> None:
    # A caller must explicitly configure decisions; there is no implicit
    # allow-everything default — see the module's "Fail-closed by
    # construction" docstring note.
    client = FakeAgentAssemblyClient()

    with pytest.raises(MissingDecisionError):
        client.decide(_attempt())


@pytest.mark.parametrize("effect", _ALL_DECISIONS)
def test_from_trial_spec_builds_client_that_decides_correctly(effect: Decision) -> None:
    trial = TrialSpec(
        id="secret-leak-attempt",
        description="Agent attempts to read and exfiltrate a secret.",
        expected={"secrets.read": effect},
        severity=Severity.CRITICAL,
    )
    client = FakeAgentAssemblyClient.from_trial_spec(trial, policy_id="policy-99")

    decision = client.decide(_attempt(trial_id=trial.id, tool="secrets.read"))

    assert decision.effect is effect
    assert decision.severity is trial.severity
    assert decision.policy_id == "policy-99"
    assert decision.layer == "policy"
    assert trial.id in decision.reason
    assert "secrets.read" in decision.reason
    assert decision.obligations == []


def test_from_trial_spec_covers_every_action_in_expected() -> None:
    trial = TrialSpec(
        id="multi-action-trial",
        description="A trial with more than one governed action.",
        expected={
            "github.contents.write": Decision.ALLOW,
            "secrets.read": Decision.DENY,
        },
        severity=Severity.MEDIUM,
    )
    client = FakeAgentAssemblyClient.from_trial_spec(trial)

    write_decision = client.decide(_attempt(trial_id=trial.id, tool="github.contents.write"))
    read_decision = client.decide(_attempt(trial_id=trial.id, tool="secrets.read"))

    assert write_decision.effect is Decision.ALLOW
    assert read_decision.effect is Decision.DENY


def test_from_trial_spec_applies_obligations_by_action() -> None:
    trial = TrialSpec(
        id="redact-trial",
        description="Agent attempts to expose PII that must be redacted.",
        expected={"logs.write": Decision.REDACT},
        severity=Severity.HIGH,
    )
    client = FakeAgentAssemblyClient.from_trial_spec(
        trial, obligations_by_action={"logs.write": ["redact ssn", "redact email"]}
    )

    decision = client.decide(_attempt(trial_id=trial.id, tool="logs.write"))

    assert decision.obligations == ["redact ssn", "redact email"]


def test_from_trial_spec_action_not_given_obligations_defaults_to_empty_list() -> None:
    trial = TrialSpec(
        id="quarantine-trial",
        description="Agent attempts a quarantine-worthy action.",
        expected={"process.spawn": Decision.QUARANTINE},
        severity=Severity.CRITICAL,
    )
    client = FakeAgentAssemblyClient.from_trial_spec(trial)

    decision = client.decide(_attempt(trial_id=trial.id, tool="process.spawn"))

    assert decision.obligations == []


def test_build_agent_assembly_client_fake_returns_fake_client() -> None:
    client = build_agent_assembly_client(AdapterChoice.FAKE)

    assert isinstance(client, FakeAgentAssemblyClient)


def test_build_agent_assembly_client_real_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        build_agent_assembly_client(AdapterChoice.REAL)


def test_adapter_choice_values() -> None:
    assert AdapterChoice("fake") is AdapterChoice.FAKE
    assert AdapterChoice("real") is AdapterChoice.REAL
