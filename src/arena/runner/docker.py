"""`DockerRunner`: executes a manifest-described agent inside a container.

This is AAASM-4375's execution backend for `EntrypointType.DOCKER` manifests
(`arena.models.manifest.AgentEntrypoint`), matching the `Runner` protocol
(`arena.runner.base`) that AAASM-4374's `ProcessRunner` also implements. The
MVP match rotation is expected to run mostly through `ProcessRunner` for
official agents — see `docs/runners.md` for when to reach for this runner
instead.

Because Arena runs agent plugin code that may be submitted by the public
(`CONTRIBUTING.md`, "Security: untrusted code and secrets"), every container
this runner starts is launched with conservative, hardcoded-safe defaults:
no `--privileged`, an explicit `--workdir`, a bounded wall-clock timeout, and
**no host environment or secret passthrough** — only the key/value pairs a
manifest's `entrypoint.env` explicitly declares are set inside the
container. Full hardened sandboxing (seccomp/AppArmor profiles, network
policy, Kubernetes) is out of scope here; this runner's job is to not do
anything *obviously* unsafe by default, not to be a complete sandbox.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from arena.models.manifest import AgentManifest
from arena.models.scenario import TrialSpec
from arena.runner.base import AgentRunResult

#: Explicit in-container working directory every container is started with,
#: rather than leaving it to the image's own default. Fixed (not
#: manifest-configurable) so a submitted manifest can't redirect execution
#: to an unexpected path.
CONTAINER_WORKDIR = "/workspace"

#: Default wall-clock budget for one container run. Conservative because
#: match orchestration (`arena.runner.match.run_match`) runs many trials
#: sequentially and a hung community-submitted agent must not stall an
#: entire match. Mirrors the constructor-configurable-with-a-safe-default
#: shape `ProcessRunner` (AAASM-4374) uses for the same reason.
DEFAULT_TIMEOUT_SECONDS = 120.0

#: Injectable seam so tests can exercise `DockerRunner` without a live
#: Docker daemon — see `docs/runners.md` for why this repo's tests use it.
CommandRunner = Callable[..., "subprocess.CompletedProcess[str]"]


class DockerRunner:
    """Launches one agent inside a Docker container for one trial.

    `run` never raises for a missing image reference, an unavailable Docker
    daemon/CLI, an image pull failure, or a container launch/timeout
    failure — each is converted into a non-zero-exit-code `AgentRunResult`
    so match orchestration gets a reportable result instead of a crash, per
    the `Runner` protocol's contract (see `arena.runner.base.Runner.run`'s
    docstring).
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        docker_binary: str = "docker",
        command_runner: CommandRunner = subprocess.run,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._docker_binary = docker_binary
        # Real code always calls `subprocess.run`; tests substitute a stub
        # so they can assert on the constructed `docker run` argv without
        # depending on a live Docker daemon being available.
        self._command_runner = command_runner

    def run(
        self,
        manifest: AgentManifest,
        _trial: TrialSpec,
        *,
        workspace: Path,
    ) -> AgentRunResult:
        started = time.monotonic()
        workspace.mkdir(parents=True, exist_ok=True)

        image = manifest.entrypoint.image
        if not image:
            return AgentRunResult(
                exit_code=1,
                stdout="",
                stderr=(
                    f"DockerRunner requires manifest.entrypoint.image "
                    f"(agent {manifest.id!r} has none set)"
                ),
                duration_seconds=time.monotonic() - started,
            )

        argv = self._build_argv(manifest, image=image)

        try:
            completed = self._command_runner(
                argv,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            # `TimeoutExpired.stdout`/`.stderr` are typed `bytes | str | None`
            # (the exception class isn't parameterized by the `text=True` we
            # always pass), so normalize defensively before building the result.
            captured_stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout
            captured_stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr
            return AgentRunResult(
                exit_code=124,
                stdout=captured_stdout or "",
                stderr=(
                    (captured_stderr or "")
                    + f"\n[docker-runner] timed out after {self._timeout_seconds}s"
                ),
                duration_seconds=time.monotonic() - started,
            )
        except OSError as exc:
            # Docker CLI missing, daemon unreachable, or the container
            # otherwise failed to launch (e.g. image pull failure surfaced
            # as a non-zero exit from `docker run` is handled by the
            # `completed` branch above; this is for launch itself failing).
            return AgentRunResult(
                exit_code=1,
                stdout="",
                stderr=f"[docker-runner] failed to launch container: {exc}",
                duration_seconds=time.monotonic() - started,
            )

        return AgentRunResult(
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_seconds=time.monotonic() - started,
        )

    def _build_argv(self, manifest: AgentManifest, *, image: str) -> list[str]:
        """Build the `docker run` invocation with safe defaults applied.

        No `--privileged`. No `--env-file` or host environment forwarding —
        only `entrypoint.env`'s explicit key/value pairs (empty by default)
        become `--env` flags, so Arena's own process environment (which may
        hold CI/repo secrets) is never passed into the container.
        """
        argv = [
            self._docker_binary,
            "run",
            "--rm",
            "--workdir",
            CONTAINER_WORKDIR,
        ]
        for key, value in sorted(manifest.entrypoint.env.items()):
            argv.extend(["--env", f"{key}={value}"])
        argv.append(image)
        if manifest.entrypoint.command:
            argv.extend(shlex.split(manifest.entrypoint.command))
        return argv
