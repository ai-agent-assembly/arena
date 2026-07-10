"""Agent Plugin Manifest schema (`agent.yaml`).

The manifest is the plug-in contract between a submitted agent and the Arena
runner (see `docs/architecture.md`): Arena never imports or hard-codes
agent-specific logic, it only reads a manifest and invokes what it points to.
This module defines that contract as Pydantic v2 models so every caller
(the validation CLI here, and later the registry discovery in AAASM-4366)
gets identical parsing and error semantics.

Field set and the `id` identifier pattern follow AAASM-4364's proposed
design and AAASM-4365's acceptance criteria; scope is deliberately limited to
what those tickets specify rather than anticipating registry or scaffold
needs from AAASM-4366/AAASM-4367.
"""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Lowercase kebab-case: alphanumeric segments separated by single hyphens,
# no leading/trailing hyphen. Matches examples like "raw-python-issue-triager".
AGENT_ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class AgentFramework(str, Enum):
    """Framework family an agent plugin is built on.

    Covers the frameworks named in `docs/glossary.md` / `README.md`, plus
    `OTHER` as an escape hatch so a new framework doesn't require a schema
    change to be declared.
    """

    RAW_PYTHON = "raw-python"
    LANGGRAPH = "langgraph"
    CREWAI = "crewai"
    PYDANTIC_AI = "pydantic-ai"
    AUTOGEN = "autogen"
    OTHER = "other"


class EntrypointType(str, Enum):
    """How Arena's runner should start the agent process."""

    COMMAND = "command"
    DOCKER = "docker"


class RuntimeType(str, Enum):
    """Execution sandbox boundary the runner starts the agent inside.

    See `docs/architecture.md` ("Where sandboxing sits") — this is *always*
    a container or an isolated process, never unsandboxed.
    """

    PROCESS = "process"
    CONTAINER = "container"


class AgentAuthor(BaseModel):
    """Optional author/contact metadata for an agent submission."""

    model_config = ConfigDict(extra="forbid")

    github: str | None = None
    name: str | None = None
    contact: str | None = None


class AgentEntrypoint(BaseModel):
    """How Arena's runner should invoke the agent."""

    model_config = ConfigDict(extra="forbid")

    type: EntrypointType
    command: str | None = None
    image: str | None = None
    env: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_field_for_type(self) -> Self:
        if self.type is EntrypointType.COMMAND and not self.command:
            raise ValueError("entrypoint.command is required when entrypoint.type is 'command'")
        if self.type is EntrypointType.DOCKER and not self.image:
            raise ValueError("entrypoint.image is required when entrypoint.type is 'docker'")
        return self


class AgentRuntime(BaseModel):
    """Execution profile the manifest declares for the runner's sandbox."""

    model_config = ConfigDict(extra="forbid")

    type: RuntimeType


class BehaviorProfile(BaseModel):
    """A named behavior mode an agent can be tested under (AAASM-4404).

    Lets the same agent submission demonstrate multiple trial-specific
    behaviors (e.g. `normal` vs. `prompt-injection-vulnerable` vs.
    `secret-seeking`) without needing a separate agent folder per behavior —
    see `TrialSpec.behavior_id` (`arena.models.scenario`) for how a trial
    targets one of these. This subtask is schema/validation only: nothing
    yet reads `behavior_id` to actually switch what an agent process does at
    runtime (that's follow-up work, AAASM-4405/4406).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=AGENT_ID_PATTERN, min_length=2, max_length=64)
    description: str = Field(min_length=1)


class AgentManifest(BaseModel):
    """Top-level `agent.yaml` schema.

    Required fields per AAASM-4365: `id`, `name`, `framework`, `entrypoint`,
    `runtime`, `scenarios`. `author` and `capabilities` are optional
    metadata, matching AAASM-4364's example manifest. `behaviors` (AAASM-4404)
    is also optional and defaults to an empty list — an agent that declares
    none is a "legacy/simple" agent with no behavior-profile distinction,
    which keeps every manifest written before this subtask valid unchanged.
    A non-empty `behaviors` list must declare each profile explicitly (there
    is no implicit `normal` entry injected) and every `id` in it must be
    unique.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=AGENT_ID_PATTERN, min_length=2, max_length=64)
    name: str = Field(min_length=1)
    framework: AgentFramework
    entrypoint: AgentEntrypoint
    runtime: AgentRuntime
    scenarios: list[str] = Field(min_length=1)
    author: AgentAuthor | None = None
    capabilities: list[str] = Field(default_factory=list)
    behaviors: list[BehaviorProfile] = Field(default_factory=list)

    @field_validator("scenarios", "capabilities")
    @classmethod
    def _no_blank_entries(cls, value: list[str]) -> list[str]:
        if any(not entry.strip() for entry in value):
            raise ValueError("entries must not be blank")
        return value

    @field_validator("behaviors")
    @classmethod
    def _behavior_ids_are_unique(cls, value: list[BehaviorProfile]) -> list[BehaviorProfile]:
        ids = [behavior.id for behavior in value]
        duplicates = sorted({behavior_id for behavior_id in ids if ids.count(behavior_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate behavior ids: {duplicates!r}")
        return value
