"""Unit tests for the AgentManifest Pydantic schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.models.manifest import AgentFramework, AgentManifest, EntrypointType, RuntimeType

VALID_MANIFEST: dict[str, object] = {
    "id": "raw-python-issue-triager",
    "name": "Raw Python Issue Triage Agent",
    "framework": "raw-python",
    "author": {"github": "ai-agent-assembly"},
    "entrypoint": {"type": "command", "command": "uv run python main.py"},
    "runtime": {"type": "process"},
    "scenarios": ["github-maintainer-dungeon"],
    "capabilities": ["github.issue.read", "github.issue.label", "github.comment.write"],
}


def test_valid_manifest_parses() -> None:
    manifest = AgentManifest.model_validate(VALID_MANIFEST)

    assert manifest.id == "raw-python-issue-triager"
    assert manifest.framework is AgentFramework.RAW_PYTHON
    assert manifest.entrypoint.type is EntrypointType.COMMAND
    assert manifest.runtime.type is RuntimeType.PROCESS
    assert manifest.scenarios == ["github-maintainer-dungeon"]
    assert manifest.author is not None
    assert manifest.author.github == "ai-agent-assembly"


def test_minimal_manifest_without_optional_fields_parses() -> None:
    minimal = {
        "id": "minimal-agent",
        "name": "Minimal Agent",
        "framework": "other",
        "entrypoint": {"type": "command", "command": "python main.py"},
        "runtime": {"type": "process"},
        "scenarios": ["some-scenario"],
    }

    manifest = AgentManifest.model_validate(minimal)

    assert manifest.author is None
    assert manifest.capabilities == []


@pytest.mark.parametrize(
    "missing_field",
    ["id", "name", "framework", "entrypoint", "runtime", "scenarios"],
)
def test_missing_required_field_raises(missing_field: str) -> None:
    payload = dict(VALID_MANIFEST)
    del payload[missing_field]

    with pytest.raises(ValidationError) as exc_info:
        AgentManifest.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(error["loc"] == (missing_field,) for error in errors)


@pytest.mark.parametrize(
    "bad_id",
    ["Bad_Agent_ID", "-leading-hyphen", "trailing-hyphen-", "has space", "UPPER"],
)
def test_unsafe_id_pattern_raises(bad_id: str) -> None:
    payload = dict(VALID_MANIFEST) | {"id": bad_id}

    with pytest.raises(ValidationError) as exc_info:
        AgentManifest.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("id",) for error in errors)


def test_empty_scenarios_list_raises() -> None:
    payload = dict(VALID_MANIFEST) | {"scenarios": []}

    with pytest.raises(ValidationError) as exc_info:
        AgentManifest.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("scenarios",) for error in errors)


def test_command_entrypoint_without_command_raises() -> None:
    payload = dict(VALID_MANIFEST) | {"entrypoint": {"type": "command"}}

    with pytest.raises(ValidationError) as exc_info:
        AgentManifest.model_validate(payload)

    errors = exc_info.value.errors()
    assert any("entrypoint" in error["loc"] for error in errors)


def test_docker_entrypoint_without_image_raises() -> None:
    payload = dict(VALID_MANIFEST) | {"entrypoint": {"type": "docker"}}

    with pytest.raises(ValidationError) as exc_info:
        AgentManifest.model_validate(payload)

    errors = exc_info.value.errors()
    assert any("entrypoint" in error["loc"] for error in errors)


def test_docker_entrypoint_with_image_parses() -> None:
    payload = dict(VALID_MANIFEST) | {
        "entrypoint": {"type": "docker", "image": "ghcr.io/example/agent:latest"}
    }

    manifest = AgentManifest.model_validate(payload)

    assert manifest.entrypoint.type is EntrypointType.DOCKER
    assert manifest.entrypoint.image == "ghcr.io/example/agent:latest"


def test_unknown_field_raises() -> None:
    payload = dict(VALID_MANIFEST) | {"unexpected_field": "surprise"}

    with pytest.raises(ValidationError) as exc_info:
        AgentManifest.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("unexpected_field",) for error in errors)
