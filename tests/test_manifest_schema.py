"""Unit tests for the AgentManifest Pydantic schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.models.manifest import (
    AgentFramework,
    AgentManifest,
    BehaviorProfile,
    EntrypointType,
    RuntimeType,
)

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


# --- behaviors (AAASM-4404) ---------------------------------------------------


def test_manifest_without_behaviors_defaults_to_empty_list() -> None:
    # Backward compatibility: a manifest written before AAASM-4404 declares
    # no `behaviors` key at all and must still parse as a "legacy/simple"
    # agent with no behavior-profile distinction.
    manifest = AgentManifest.model_validate(VALID_MANIFEST)

    assert manifest.behaviors == []


def test_manifest_with_multiple_behaviors_parses() -> None:
    payload = dict(VALID_MANIFEST) | {
        "behaviors": [
            {"id": "normal", "description": "Ordinary, compliant behavior."},
            {"id": "secret-seeking", "description": "Attempts to read a secrets file."},
        ]
    }

    manifest = AgentManifest.model_validate(payload)

    assert [behavior.id for behavior in manifest.behaviors] == ["normal", "secret-seeking"]
    assert all(isinstance(behavior, BehaviorProfile) for behavior in manifest.behaviors)


def test_duplicate_behavior_ids_raises() -> None:
    payload = dict(VALID_MANIFEST) | {
        "behaviors": [
            {"id": "normal", "description": "First declaration."},
            {"id": "normal", "description": "Second, conflicting declaration."},
        ]
    }

    with pytest.raises(ValidationError, match="duplicate behavior ids"):
        AgentManifest.model_validate(payload)


@pytest.mark.parametrize(
    "bad_id",
    ["Bad_Behavior", "-leading-hyphen", "trailing-hyphen-", "has space", "UPPER"],
)
def test_behavior_profile_invalid_id_pattern_raises(bad_id: str) -> None:
    payload = dict(VALID_MANIFEST) | {
        "behaviors": [{"id": bad_id, "description": "A behavior with a bad id."}]
    }

    with pytest.raises(ValidationError) as exc_info:
        AgentManifest.model_validate(payload)

    errors = exc_info.value.errors()
    assert any("behaviors" in error["loc"] and "id" in error["loc"] for error in errors)


def test_behavior_profile_empty_description_raises() -> None:
    with pytest.raises(ValidationError):
        BehaviorProfile.model_validate({"id": "normal", "description": ""})


def test_behavior_profile_unknown_field_raises() -> None:
    with pytest.raises(ValidationError):
        BehaviorProfile.model_validate(
            {"id": "normal", "description": "Ordinary behavior.", "unexpected_field": "surprise"}
        )
