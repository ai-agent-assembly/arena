"""`ProcessRunner`: the `Runner` for `EntrypointType.COMMAND` agent plugins.

Launches `manifest.entrypoint.command` as a local subprocess, feeds it match
and trial context, and reports back a uniform `AgentRunResult` — including
when the process times out or never starts. Per the `Runner` protocol
contract (`arena.runner.base`), this never raises for an ordinary agent
failure; every failure mode below is converted into a non-zero
`AgentRunResult` instead, so one broken agent process cannot crash the rest
of a match.

**Context delivery.** Trial/match context is passed to the agent process via
environment variables, not JSON over stdin. Env vars are the simpler of the
two options AAASM-4374 allows: every subprocess-capable language/framework
can read them with zero parsing code, whereas stdin would require every
agent entrypoint to agree on a stdin-JSON protocol before it can do anything
else. The variables set (see `_build_env`) are `ARENA_AGENT_ID`,
`ARENA_TRIAL_ID`, `ARENA_TRIAL_DESCRIPTION`, `ARENA_TRIAL_SEVERITY`, and
`ARENA_WORKSPACE` — the subset of `TrialSpec`/`AgentManifest` that's
generically useful to any agent regardless of framework. `expected` is
deliberately not passed: leaking the expected governance decision to the
agent under test would let it game the trial instead of behaving naturally.
The manifest's own `entrypoint.env` (declared in `agent.yaml`) is merged in
underneath the `ARENA_*` vars, and a small allowlist of the parent process's
environment (`_SAFE_BASE_ENV_VARS`) underneath that, so `ARENA_*` context
always wins if a name collides.

**Host environment is NOT inherited wholesale.** Only the names in
`_SAFE_BASE_ENV_VARS` are copied from Arena's own process environment; the
rest (which may hold CI/repo secrets — API tokens, cloud credentials, signing
keys) never reach the agent subprocess. This mirrors `DockerRunner`'s "no host
env or secret passthrough" contract: a command-type agent runs on the Arena
host without the container boundary, so leaking the full parent environment
into it would hand any submitted `entrypoint.command` every secret in Arena's
own environment. The allowlist is deliberately the minimum a subprocess
generally needs to locate its interpreter/toolchain and behave sanely
(`PATH`/`HOME` to launch, locale/`TMPDIR`/`TZ` for correct runtime behavior);
anything an agent genuinely needs beyond that is declared explicitly in its
manifest `entrypoint.env`.

**Working directory.** The subprocess is launched with `cwd=workspace` — the
per-(agent, trial) directory `arena.runner.match.run_match` already creates
and passes in. This is a real constraint, not just a preference: the
`Runner.run` signature (frozen by AAASM-4373) receives `AgentManifest`, which
has no path field, so `ProcessRunner` has no way to know where the agent's
own plugin directory lives on disk — `workspace` is the only directory this
call is guaranteed to have and be allowed to write under. A relative
`entrypoint.command` therefore resolves relative to the trial workspace, not
the agent's submission directory; an agent entrypoint that needs its own
files at runtime must reference them by an absolute or otherwise
self-locating path (e.g. resolve relative to `sys.argv[0]`/`__file__`) rather
than assuming its source directory is the current working directory.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

from arena.models.manifest import AgentManifest
from arena.models.scenario import TrialSpec
from arena.runner.base import AgentRunResult

#: Generous enough for a short-lived triage/decision script, short enough
#: that one hung or looping agent process can't stall a whole match run.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: Synthetic exit codes for failures that never produced a real process exit
#: status, chosen to match familiar shell conventions (`timeout`'s 124,
#: "command not found"'s 127) so they read as recognizable signals rather
#: than arbitrary numbers.
_TIMEOUT_EXIT_CODE = 124
_LAUNCH_FAILURE_EXIT_CODE = 127

#: The only names copied from Arena's own process environment into an agent
#: subprocess. Everything else (CI/repo secrets, cloud credentials, tokens) is
#: withheld — see this module's docstring for why a command-type agent must not
#: inherit the full host environment. Kept to what a subprocess generally needs
#: to find its interpreter/toolchain (`PATH`, `HOME`) and behave correctly
#: (locale, temp dir, timezone); an agent needing anything else declares it in
#: its manifest `entrypoint.env`.
_SAFE_BASE_ENV_VARS = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TZ",
    }
)


def _build_env(manifest: AgentManifest, trial: TrialSpec, *, workspace: Path) -> dict[str, str]:
    """A safe base-env allowlist, overlaid with the manifest's declared env,
    overlaid with Arena's own trial context — later entries win on key
    collision. The full host environment is deliberately not inherited (see
    the module docstring): only `_SAFE_BASE_ENV_VARS` present in `os.environ`
    are carried through.
    """
    base_env = {name: os.environ[name] for name in _SAFE_BASE_ENV_VARS if name in os.environ}
    return {
        **base_env,
        **manifest.entrypoint.env,
        "ARENA_AGENT_ID": manifest.id,
        "ARENA_TRIAL_ID": trial.id,
        "ARENA_TRIAL_DESCRIPTION": trial.description,
        "ARENA_TRIAL_SEVERITY": trial.severity.value,
        "ARENA_WORKSPACE": str(workspace),
    }


class ProcessRunner:
    """Executes a command-type agent entrypoint as a local subprocess.

    `timeout_seconds` is configurable per instance (constructor arg) so
    callers can tighten or loosen it per scenario/CI environment; it defaults
    to `DEFAULT_TIMEOUT_SECONDS`.
    """

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def run(
        self,
        manifest: AgentManifest,
        trial: TrialSpec,
        *,
        workspace: Path,
    ) -> AgentRunResult:
        workspace.mkdir(parents=True, exist_ok=True)

        command = manifest.entrypoint.command
        # AgentEntrypoint._require_field_for_type already guarantees this for
        # EntrypointType.COMMAND; the assert documents that invariant here
        # rather than silently coping with a None command.
        assert command is not None, "command entrypoint must declare entrypoint.command"

        env = _build_env(manifest, trial, workspace=workspace)
        started = time.monotonic()

        try:
            completed = subprocess.run(
                shlex.split(command),
                cwd=workspace,
                env=env,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self._timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            partial_stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return AgentRunResult(
                exit_code=_TIMEOUT_EXIT_CODE,
                stdout=exc.stdout if isinstance(exc.stdout, str) else "",
                stderr=(
                    f"{partial_stderr}"
                    f"[arena.ProcessRunner] agent process timed out after "
                    f"{self._timeout_seconds}s (command={command!r}); this is a "
                    "runner-enforced timeout, not a real process exit\n"
                ),
                duration_seconds=duration,
            )
        except OSError as exc:
            # Command not found, not executable, permission denied, etc. —
            # the process never started, so there's nothing to capture.
            duration = time.monotonic() - started
            return AgentRunResult(
                exit_code=_LAUNCH_FAILURE_EXIT_CODE,
                stdout="",
                stderr=(f"[arena.ProcessRunner] failed to launch command {command!r}: {exc}\n"),
                duration_seconds=duration,
            )

        duration = time.monotonic() - started
        return AgentRunResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
        )
