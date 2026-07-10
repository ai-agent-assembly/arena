"""Load and validate agent plugin manifests from `agent.yaml` files on disk.

Kept as the single place that turns a YAML file into a validated
`AgentManifest`, so every caller (the CLI here, and later the registry
discovery in AAASM-4366) gets identical error handling.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from arena.models.manifest import AgentManifest


class ManifestLoadError(Exception):
    """Raised when a manifest file is missing or is not valid YAML.

    Schema validation failures raise `pydantic.ValidationError` directly
    instead, so callers can format field-level errors from `.errors()`.
    """


def load_manifest(path: Path) -> AgentManifest:
    """Load and validate an `AgentManifest` from a YAML file.

    Raises:
        ManifestLoadError: the file is missing or is not valid YAML.
        pydantic.ValidationError: the YAML parses but fails schema validation.
    """
    if not path.is_file():
        raise ManifestLoadError(f"manifest file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ManifestLoadError(f"failed to parse YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestLoadError(
            f"manifest {path} must contain a YAML mapping, got {type(raw).__name__}"
        )

    return AgentManifest.model_validate(raw)
