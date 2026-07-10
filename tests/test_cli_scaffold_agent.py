"""CLI tests for `aasm-arena scaffold-agent`."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from arena.agents.loader import load_manifest
from arena.cli import TEMPLATE_DIR, app

runner = CliRunner()

# Patterns that look like real credential material — the templates should
# only ever contain plain placeholder tokens, never anything shaped like this.
SECRET_LIKE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
]


def test_scaffold_agent_creates_expected_files(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "scaffold-agent",
            "--id",
            "my-test-agent",
            "--framework",
            "raw-python",
            "--output",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    target = tmp_path / "my-test-agent"
    assert (target / "agent.yaml").is_file()
    assert (target / "README.md").is_file()
    assert (target / "main.py").is_file()


def test_scaffold_agent_generated_manifest_validates(tmp_path: Path) -> None:
    """The real `load_manifest` loader (not a re-implementation) must accept it."""
    result = runner.invoke(
        app,
        [
            "scaffold-agent",
            "--id",
            "another-agent",
            "--framework",
            "crewai",
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.stdout

    manifest = load_manifest(tmp_path / "another-agent" / "agent.yaml")
    assert manifest.id == "another-agent"
    assert manifest.framework.value == "crewai"


def test_scaffold_agent_output_passes_agents_validate_command(tmp_path: Path) -> None:
    scaffold_result = runner.invoke(
        app,
        [
            "scaffold-agent",
            "--id",
            "cli-validated-agent",
            "--framework",
            "langgraph",
            "--output",
            str(tmp_path),
        ],
    )
    assert scaffold_result.exit_code == 0, scaffold_result.stdout

    validate_result = runner.invoke(
        app, ["agents", "validate", str(tmp_path / "cli-validated-agent" / "agent.yaml")]
    )
    assert validate_result.exit_code == 0, validate_result.stdout


def test_scaffold_agent_rejects_invalid_id(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "scaffold-agent",
            "--id",
            "Not_Valid",
            "--framework",
            "raw-python",
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert not (tmp_path / "Not_Valid").exists()


def test_scaffold_agent_rejects_invalid_framework(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "scaffold-agent",
            "--id",
            "valid-id",
            "--framework",
            "not-a-real-framework",
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert not (tmp_path / "valid-id").exists()


def test_scaffold_agent_refuses_to_overwrite_existing_dir(tmp_path: Path) -> None:
    args = [
        "scaffold-agent",
        "--id",
        "dup-agent",
        "--framework",
        "raw-python",
        "--output",
        str(tmp_path),
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout

    second = runner.invoke(app, args)
    assert second.exit_code != 0


def test_scaffold_agent_readme_explains_local_run(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "scaffold-agent",
            "--id",
            "readme-agent",
            "--framework",
            "raw-python",
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.stdout

    readme = (tmp_path / "readme-agent" / "README.md").read_text()
    assert "uv run python main.py" in readme
    assert "## Running locally" in readme


def test_template_files_have_no_secret_shaped_strings() -> None:
    for template_file in TEMPLATE_DIR.glob("*.tmpl"):
        text = template_file.read_text()
        for pattern in SECRET_LIKE_PATTERNS:
            assert not pattern.search(text), f"{template_file} contains secret-shaped string"
