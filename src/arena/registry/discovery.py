"""Discover agent plugin manifests under `agents/official/` and `agents/community/`.

Layout convention, mirroring the scenario registry's convention in
`arena.scenarios.loader`:

    <root>/
        <agent-id>/
            agent.yaml   # an AgentManifest, validated via arena.agents.loader

`discover_agents` walks the official and community roots, loads every
`agent.yaml` it finds via the AAASM-4365 manifest loader, and returns an
`AgentRegistry` that Arena (and the `agents list` CLI) can filter by
framework, scenario, or source (official vs. community).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import ValidationError

from arena.agents.loader import ManifestLoadError, load_manifest
from arena.models.manifest import AgentFramework, AgentManifest

_MANIFEST_FILENAME = "agent.yaml"


class AgentSource(str, Enum):
    """Which registry root an agent manifest was discovered under."""

    OFFICIAL = "official"
    COMMUNITY = "community"


class RegistryLoadError(Exception):
    """Raised when a manifest under a registry root fails to load or validate,
    or when two manifests declare the same agent id.
    """


@dataclass(frozen=True)
class RegisteredAgent:
    """An `AgentManifest` together with where it was discovered."""

    manifest: AgentManifest
    source: AgentSource
    path: Path


@dataclass(frozen=True)
class AgentRegistry:
    """The full set of agent manifests discovered across official + community roots."""

    agents: tuple[RegisteredAgent, ...]

    def __len__(self) -> int:
        return len(self.agents)

    def filter(
        self,
        *,
        framework: AgentFramework | None = None,
        scenario: str | None = None,
        source: AgentSource | None = None,
    ) -> list[RegisteredAgent]:
        """Return agents matching all of the given filters.

        Any filter left as `None` is not applied. `scenario` matches agents
        whose manifest `scenarios` list contains that scenario id.
        """
        return [
            agent
            for agent in self.agents
            if (framework is None or agent.manifest.framework is framework)
            and (scenario is None or scenario in agent.manifest.scenarios)
            and (source is None or agent.source is source)
        ]


def _discover_source(root: Path, source: AgentSource) -> list[RegisteredAgent]:
    if not root.is_dir():
        return []

    discovered: list[RegisteredAgent] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / _MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        try:
            manifest = load_manifest(manifest_path)
        except ManifestLoadError as exc:
            raise RegistryLoadError(str(exc)) from exc
        except ValidationError as exc:
            raise RegistryLoadError(f"{manifest_path}: invalid manifest — {exc}") from exc
        discovered.append(RegisteredAgent(manifest=manifest, source=source, path=manifest_path))

    return discovered


def discover_agents(official_root: Path, community_root: Path) -> AgentRegistry:
    """Discover and validate all agent manifests under the given registry roots.

    A root directory that doesn't exist contributes zero agents rather than
    raising — an empty (or not-yet-created) registry is a valid state.

    Raises:
        RegistryLoadError: a manifest fails to load/validate, or the same
            agent id is declared more than once across official + community.
    """
    discovered = _discover_source(official_root, AgentSource.OFFICIAL) + _discover_source(
        community_root, AgentSource.COMMUNITY
    )

    seen: dict[str, RegisteredAgent] = {}
    for agent in discovered:
        agent_id = agent.manifest.id
        if agent_id in seen:
            raise RegistryLoadError(
                f"duplicate agent id {agent_id!r}: defined in both "
                f"{seen[agent_id].path} and {agent.path}"
            )
        seen[agent_id] = agent

    return AgentRegistry(agents=tuple(discovered))
