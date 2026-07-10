"""Adversarial contract tests for the attempt -> decision -> audit pipeline
(AAASM-4381), the last subtask in AAASM-4377's chain.

Where `test_integrations_adapter.py`/`test_integrations_audit.py`/
`test_runner_match.py` prove the mechanism works *when used correctly*,
this file is deliberately adversarial: it exists to make it hard (ideally
impossible) for a future change to silently violate the product's core
invariant — *Arena must never report a trial result unless every parsed
`ArenaActionAttempt` reached the configured `AgentAssemblyClient` and got a
decision recorded to the audit trail, decided or missing*.

**Why self-contained fixtures, not `github-maintainer-dungeon`.** A related,
already-filed follow-up (AAASM-4408, "Make trial expected-decision mapping
agent-role-aware") tracks a real, separate gap: several trials in the real
`github-maintainer-dungeon` scenario have `expected` mappings that don't
anticipate every action a given official agent actually attempts, so running
that scenario today shows a mix of PASS/FAIL for scenario-content reasons,
not governance-mechanism reasons. Asserting specific pass/fail counts against
that scenario here would make these contract tests either wrong today or
liable to break the moment AAASM-4408 lands — neither of which has anything
to do with what this ticket is protecting. Every test below instead builds
its own small `TrialSpec`/`ArenaActionAttempt`/`FakeAgentAssemblyClient`
(directly or via a purpose-built scenario+agent fixture), so these tests stay
valid regardless of how AAASM-4408 is eventually resolved.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from unittest.mock import patch

from arena.integrations.adapter import FakeAgentAssemblyClient
from arena.integrations.decision import DefenseDecision
from arena.integrations.models import ArenaActionAttempt
from arena.models.scenario import Decision, Severity
from arena.runner.match import MatchConfig, run_match

# --- self-contained scenario/agent fixtures ----------------------------------
#
# Deliberately minimal, purpose-built versions of the fixture helpers in
# `test_runner_match.py` rather than importing them — this file's tests must
# stand on their own, with no dependency on another test module's fixture
# shape changing out from under them.

_EMIT_AGENT_SCRIPT_TEMPLATE = '''\
"""Test-only agent: emits one ArenaActionAttempt per configured action for
its current trial, then exits 0."""
import os

from arena.integrations.emit import emit_action_attempt

_ACTIONS_BY_TRIAL = {actions_json}

trial_id = os.environ.get("ARENA_TRIAL_ID", "")
for tool, resource, args in _ACTIONS_BY_TRIAL.get(trial_id, []):
    emit_action_attempt(
        tool=tool,
        resource=resource,
        framework="raw-python",
        scenario_id={scenario_id!r},
        args=args,
    )
'''


def _write_scenario(
    root: Path,
    scenario_id: str,
    trial_id: str,
    expected: dict[str, str],
    severity: str = "high",
) -> None:
    scenario_dir = root / scenario_id
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        f"id: {scenario_id}\n"
        f"name: Contract Test Scenario\n"
        f"description: Scenario used for AAASM-4381 adversarial contract tests.\n"
        f"trials:\n"
        f"  - {trial_id}\n"
    )
    expected_yaml = "\n".join(f"  {action}: {decision}" for action, decision in expected.items())
    (trials_dir / f"{trial_id}.yaml").write_text(
        f"id: {trial_id}\n"
        f"description: A trial used for AAASM-4381 adversarial contract tests.\n"
        f"expected:\n{expected_yaml}\n"
        f"severity: {severity}\n"
    )


def _write_emitting_agent(
    official_root: Path,
    agent_id: str,
    scenario_id: str,
    actions_by_trial: dict[str, list[tuple[str, str, dict[str, str]]]],
) -> None:
    agent_dir = official_root / agent_id
    agent_dir.mkdir(parents=True)
    script_path = agent_dir / "main.py"
    script_path.write_text(
        _EMIT_AGENT_SCRIPT_TEMPLATE.format(
            actions_json=json.dumps(actions_by_trial), scenario_id=scenario_id
        )
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))}"
    (agent_dir / "agent.yaml").write_text(
        f"id: {agent_id}\n"
        f"name: {agent_id.title()}\n"
        f"framework: raw-python\n"
        f"entrypoint:\n"
        f"  type: command\n"
        f'  command: "{command}"\n'
        f"runtime:\n"
        f"  type: process\n"
        f"scenarios:\n"
        f"  - {scenario_id}\n"
    )


def _match_config(tmp_path: Path, scenarios_root: Path, official_root: Path) -> MatchConfig:
    return MatchConfig(
        scenarios_root=scenarios_root,
        official_root=official_root,
        community_root=tmp_path / "agents" / "community",
        output_root=tmp_path / "runs",
    )


def _attempt(
    *,
    tool: str = "github.contents.write",
    trial_id: str = "trial-a",
    args: dict[str, str] | None = None,
) -> ArenaActionAttempt:
    return ArenaActionAttempt(
        agent_id="agent-a",
        framework="raw-python",
        scenario_id="contract-scenario",
        trial_id=trial_id,
        tool=tool,
        resource="src/app.py",
        args=args or {},
    )


def _decision(effect: Decision, *, severity: Severity = Severity.HIGH) -> DefenseDecision:
    return DefenseDecision(
        effect=effect,
        layer="policy",
        reason=f"canned decision for {effect.value}",
        severity=severity,
    )


# --- 1. Every attempt reaches the adapter — proof against bypass -------------


def test_run_match_calls_adapter_decide_exactly_once_per_parsed_attempt(tmp_path: Path) -> None:
    """`run_match`'s loop in `arena.runner.match` calls `client.decide(attempt)`
    for every `ArenaActionAttempt` in `parse_result.attempts` — unconditionally,
    with no branch that can skip it (confirmed by reading `run_match`'s source:
    the `for attempt in parse_result.attempts:` loop's very first statement is
    the `client.decide(attempt)` call, wrapped only in a `try/except
    MissingDecisionError` that still records an audit event either way — see
    tests 2/3 below).

    This test proves that structurally, not just by inspection: it wraps the
    *real* `FakeAgentAssemblyClient.decide` (the same object `run_match`
    actually calls, since `arena.runner.match` imports the class itself, not
    a copy of it) with a counting spy that still delegates to the original
    implementation, so decisions/audit behavior are unaffected. If a future
    change to `run_match` ever introduced a path that skips the adapter for
    some attempt (e.g. a "trusted agent" shortcut, or a silent `continue`
    before the call), this test fails: the spy's call count would no longer
    match the number of attempts the agent actually emitted.
    """
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    _write_scenario(
        scenarios_root,
        "contract-scenario",
        "bypass-trial",
        {"known.action": "allow"},
    )
    # One configured action and two unconfigured ones: the adapter-bypass
    # invariant must hold regardless of whether a decision is even available,
    # since "no decision configured" and "adapter was never asked" are
    # different failure modes and only the latter is what this test guards.
    actions: dict[str, list[tuple[str, str, dict[str, str]]]] = {
        "bypass-trial": [
            ("known.action", "some/resource", {}),
            ("unlisted.action.one", "some/resource", {}),
            ("unlisted.action.two", "some/resource", {}),
        ]
    }
    _write_emitting_agent(official_root, "emit-agent", "contract-scenario", actions)

    original_decide = FakeAgentAssemblyClient.decide
    observed_attempts: list[ArenaActionAttempt] = []

    def _spy_decide(self: FakeAgentAssemblyClient, attempt: ArenaActionAttempt) -> DefenseDecision:
        observed_attempts.append(attempt)
        return original_decide(self, attempt)

    with patch.object(FakeAgentAssemblyClient, "decide", _spy_decide):
        run_match("contract-scenario", _match_config(tmp_path, scenarios_root, official_root))

    assert len(observed_attempts) == 3
    assert {a.tool for a in observed_attempts} == {
        "known.action",
        "unlisted.action.one",
        "unlisted.action.two",
    }
