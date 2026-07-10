"""Unit tests for the YAML -> AgentManifest loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from arena.agents.loader import ManifestLoadError, load_manifest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "manifests"
EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "manifests"
VALID_MANIFEST_PATH = EXAMPLES_DIR / "raw-python-issue-triager.yaml"
INVALID_MANIFEST_PATH = FIXTURES_DIR / "invalid.yaml"


def test_load_valid_manifest() -> None:
    manifest = load_manifest(VALID_MANIFEST_PATH)

    assert manifest.id == "raw-python-issue-triager"
    assert manifest.scenarios == ["github-maintainer-dungeon"]


def test_load_invalid_manifest_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        load_manifest(INVALID_MANIFEST_PATH)


def test_load_missing_file_raises_manifest_load_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.yaml"

    with pytest.raises(ManifestLoadError):
        load_manifest(missing)


def test_load_malformed_yaml_raises_manifest_load_error(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("id: [unterminated\n")

    with pytest.raises(ManifestLoadError):
        load_manifest(malformed)


def test_load_non_mapping_yaml_raises_manifest_load_error(tmp_path: Path) -> None:
    non_mapping = tmp_path / "list.yaml"
    non_mapping.write_text("- one\n- two\n")

    with pytest.raises(ManifestLoadError):
        load_manifest(non_mapping)
