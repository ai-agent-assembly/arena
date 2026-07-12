"""LLM execution mode policy (AAASM-4405).

Arena stays deterministic and zero-cost by default: `LLMMode.MOCK` (the
default everywhere — `MatchConfig.llm_mode`, `aasm-arena run --llm-mode`) and
`LLMMode.REPLAY` both make zero real, paid model API calls by construction —
today, no official agent (`agents/official/*/main.py`) makes a real model
call at all (`ci-debug-agent` uses `pydantic_ai.models.test.TestModel`;
every other official agent is a plain scripted `raw-python`/`langgraph`
persona with no LLM in the loop — see each agent's own module docstring),
so there is no code path for either mode to gate in the first place. This
module exists to make that a stated, enforced *policy* rather than an
incidental fact of what agents happen to exist today: any future agent or
runner integration that does add a real model call must gate it on
`MatchConfig.llm_mode`, and `LLMMode.LIVE` is the only mode allowed to take
that path.

**Why `LIVE` is opt-in, not just discouraged.** `LLMMode.LIVE` is rejected
unless `LIVE_LLM_ENV_VAR` is set to the literal string `"true"` — see
`validate_llm_mode`. This is deliberately the *only* gate, rather than a
separate "is this a fork PR" check: none of Arena's CI workflows
(`ci.yml`, `validate-community-agents.yml`, `scheduled-matches.yml`) set
`AASM_ARENA_LIVE_LLM`, and `validate-community-agents.yml` — the one
workflow that runs against untrusted fork PR content — never invokes
`aasm-arena run` at all (it only runs `aasm-arena agents validate`, which
parses manifests and never executes an agent's declared entrypoint). So a
single env-var gate is sufficient to keep `live` mode out of PR/fork CI by
construction: there is no code path in this repo's own workflows that both
runs a match *and* sets the opt-in variable.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum

#: Environment variable that must be set to the literal string `"true"` for
#: `LLMMode.LIVE` to be permitted. Any other value (including unset) rejects
#: `LIVE` — see `validate_llm_mode`.
LIVE_LLM_ENV_VAR = "AASM_ARENA_LIVE_LLM"


class LLMMode(str, Enum):
    """How a match's agents are allowed to interact with LLMs.

    `MOCK` is the default everywhere (`MatchConfig.llm_mode`,
    `aasm-arena run --llm-mode`): agents run against canned/deterministic
    model behavior (or, today, no model call at all — see the module
    docstring), making zero real API calls. `REPLAY` is likewise zero-cost
    and zero-network: it's for replaying previously recorded model
    responses rather than inventing new ones, still with no live API call.
    `LIVE` is the only mode that may make real, paid model API calls, and
    is gated behind explicit opt-in — see `validate_llm_mode`.
    """

    MOCK = "mock"
    REPLAY = "replay"
    LIVE = "live"


class LiveLLMModeNotEnabledError(Exception):
    """Raised when `LLMMode.LIVE` is requested without explicit opt-in.

    See `validate_llm_mode`.
    """


def validate_llm_mode(mode: LLMMode, *, env: Mapping[str, str] | None = None) -> None:
    """Enforce the live-mode opt-in gate.

    A no-op for `LLMMode.MOCK`/`LLMMode.REPLAY` — only `LLMMode.LIVE` is
    gated. `env` defaults to the real process environment (`os.environ`);
    tests pass an explicit mapping instead of mutating process-global state.

    Raises:
        LiveLLMModeNotEnabledError: `mode` is `LLMMode.LIVE` and
            `LIVE_LLM_ENV_VAR` is not set to `"true"` in `env`.
    """
    if mode is not LLMMode.LIVE:
        return
    active_env = env if env is not None else os.environ
    if active_env.get(LIVE_LLM_ENV_VAR) != "true":
        raise LiveLLMModeNotEnabledError(
            f"llm_mode 'live' requires {LIVE_LLM_ENV_VAR}=true to be set "
            "explicitly — refusing to make real, paid model API calls without "
            "opt-in"
        )
