"""Unit tests for the LLM execution mode policy (AAASM-4405,
`arena.runner.llm_mode`).
"""

from __future__ import annotations

import pytest

from arena.runner.llm_mode import (
    LIVE_LLM_ENV_VAR,
    LiveLLMModeNotEnabledError,
    LLMMode,
    validate_llm_mode,
)


def test_llm_mode_values() -> None:
    # AAASM-4406 depends on these exact string values — do not rename.
    assert LLMMode.MOCK.value == "mock"
    assert LLMMode.REPLAY.value == "replay"
    assert LLMMode.LIVE.value == "live"


def test_validate_llm_mode_mock_is_always_allowed() -> None:
    validate_llm_mode(LLMMode.MOCK, env={})


def test_validate_llm_mode_replay_is_always_allowed() -> None:
    validate_llm_mode(LLMMode.REPLAY, env={})


def test_validate_llm_mode_live_rejected_without_env_var() -> None:
    with pytest.raises(LiveLLMModeNotEnabledError, match=LIVE_LLM_ENV_VAR):
        validate_llm_mode(LLMMode.LIVE, env={})


def test_validate_llm_mode_live_rejected_with_wrong_value() -> None:
    with pytest.raises(LiveLLMModeNotEnabledError):
        validate_llm_mode(LLMMode.LIVE, env={LIVE_LLM_ENV_VAR: "1"})


def test_validate_llm_mode_live_allowed_when_env_var_set() -> None:
    validate_llm_mode(LLMMode.LIVE, env={LIVE_LLM_ENV_VAR: "true"})


def test_validate_llm_mode_live_reads_real_environ_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(LIVE_LLM_ENV_VAR, raising=False)
    with pytest.raises(LiveLLMModeNotEnabledError):
        validate_llm_mode(LLMMode.LIVE)

    monkeypatch.setenv(LIVE_LLM_ENV_VAR, "true")
    validate_llm_mode(LLMMode.LIVE)
