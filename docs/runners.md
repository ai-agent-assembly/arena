# Runners: process vs. Docker

Arena executes a match through one of two `Runner` implementations, selected per agent by the `entrypoint.type` declared in that agent's manifest (`arena.models.manifest.EntrypointType`). Both implement the same `Runner` protocol (`src/arena/runner/base.py`) — match orchestration (`arena.runner.match`) doesn't need to know which one it's talking to.

## `ProcessRunner` (`entrypoint.type: command`)

Starts the agent as a subprocess on the host that Arena itself runs on. This is the runner the MVP match rotation uses for **official agents**: the reference agents Arena maintains itself, whose code is already trusted and reviewed as part of the repo.

Use `ProcessRunner` when:

- The agent is an official, reviewed agent shipped in this repo.
- The agent's runtime needs are already satisfied by the CI/runner host's environment (Python, uv, etc.) with no extra isolation requirement beyond what a subprocess already gives you.

## `DockerRunner` (`entrypoint.type: docker`)

Starts the agent inside a container built from the image the manifest declares (`entrypoint.image`), via the `docker` CLI. This is the runner **community-submitted agents** are expected to use, and the one Arena leans on as its sandboxing story hardens over time (see `docs/architecture.md`, "Where sandboxing sits").

Use `DockerRunner` when:

- The agent is community-submitted, or its code isn't already reviewed/trusted.
- The agent needs a runtime/dependency set that doesn't match the CI host (a different language, non-Python tooling, pinned system packages) — a Dockerfile is the agent's own way of declaring that, rather than Arena's CI environment needing to grow special cases per agent.

### Safe defaults

`DockerRunner` (`src/arena/runner/docker.py`) applies conservative defaults to every container it starts, none of which are configurable up from a manifest:

- **No `--privileged`.** Never enabled, never manifest-configurable.
- **Explicit `--workdir`.** Every container runs with a fixed, explicit working directory rather than trusting the image's own default.
- **Bounded timeout.** A wall-clock budget (constructor `timeout_seconds`, defaulting to 120s) bounds every `docker run` invocation; a hung container is treated as a failed trial, not an indefinitely blocked match.
- **No host environment or secret passthrough.** Arena's own process environment — which may hold CI/repository secrets — is never forwarded into the container. Only the key/value pairs a manifest's `entrypoint.env` explicitly declares become `--env` flags; that field is empty by default, so a manifest gets *nothing* unless it asks for it explicitly.

**Untrusted code must never run with repository secrets.** This is not `DockerRunner`-specific — it's the repo-wide rule in `CONTRIBUTING.md` ("Security: untrusted code and secrets") and `docs/architecture.md` ("Where sandboxing sits"). `DockerRunner`'s env-passthrough default is one mechanical enforcement of that rule at the runner layer; it does not replace the CI-level controls that keep untrusted PR code out of privileged workflow contexts.

Out of scope for `DockerRunner` as it stands today: full hardened sandboxing (seccomp/AppArmor profiles, network egress policy), Kubernetes-based execution, and automatically running fork-PR agents with any secret access. Those remain research/ADR questions, not implemented behavior.

### How it's tested

`DockerRunner` shells out to the `docker` CLI via an injectable `command_runner` seam (defaulting to `subprocess.run`). The test suite (`tests/test_runner_docker.py`) exercises it entirely through a stubbed `command_runner` — asserting on the constructed `docker run` argv (e.g. that `--privileged` is never present, that `--env` only reflects `entrypoint.env`) and on canned success/failure/timeout results — rather than against a live Docker daemon. This keeps the suite deterministic and fast, and works in environments where a Docker daemon isn't running (the Docker CLI can be installed without its daemon being up, which was the case in this ticket's own development environment). If you have a live daemon available locally, you can still exercise `DockerRunner` end-to-end against a trivial local image by constructing it with the default `command_runner`.
