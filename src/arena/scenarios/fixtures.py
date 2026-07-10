"""Loader for Arena's local scenario fixtures.

Fixtures are static, offline test data (fake GitHub issues, CI logs, repo
files, and secret-shaped strings) used by scenario/trial specs — starting
with `github-maintainer-dungeon` — so trials can run deterministically
without touching real GitHub repos, CI systems, or credentials. See
`tests/fixtures/github_maintainer_dungeon/README.md` for what each fixture
represents (AAASM-4371).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

#: Fixture categories every scenario fixture set is expected to provide.
FIXTURE_CATEGORIES: Final[tuple[str, ...]] = ("issues", "ci_logs", "repo_files", "secrets")

_DEFAULT_SCENARIO: Final[str] = "github_maintainer_dungeon"


class FixtureError(Exception):
    """Raised when a fixture category or fixture file cannot be resolved."""


def _repo_root() -> Path:
    """Walk up from this file to the repository root (marked by pyproject.toml)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise FixtureError(
        "Could not locate repository root (no pyproject.toml found above fixtures.py)"
    )


def _category_dir(category: str, scenario: str = _DEFAULT_SCENARIO) -> Path:
    if category not in FIXTURE_CATEGORIES:
        raise FixtureError(
            f"Unknown fixture category {category!r}; expected one of {FIXTURE_CATEGORIES}"
        )
    category_dir = _repo_root() / "tests" / "fixtures" / scenario / category
    if not category_dir.is_dir():
        raise FixtureError(f"Fixture category directory not found: {category_dir}")
    return category_dir


def list_fixtures(category: str, scenario: str = _DEFAULT_SCENARIO) -> list[str]:
    """List fixture file names available in `category`, as paths relative to it.

    Sorted for deterministic ordering. Raises `FixtureError` if `category` is
    not a known fixture category or the category directory doesn't exist.
    """
    category_dir = _category_dir(category, scenario)
    return sorted(
        str(path.relative_to(category_dir)) for path in category_dir.rglob("*") if path.is_file()
    )


def load_fixture(category: str, name: str, scenario: str = _DEFAULT_SCENARIO) -> str:
    """Load the raw text content of a fixture file by category and relative name.

    Raises `FixtureError` if the category is unknown or `name` doesn't exist
    within it.
    """
    category_dir = _category_dir(category, scenario)
    fixture_path = category_dir / name
    if not fixture_path.is_file():
        available = ", ".join(list_fixtures(category, scenario)) or "(none)"
        raise FixtureError(
            f"Fixture {name!r} not found in category {category!r}. Available: {available}"
        )
    return fixture_path.read_text(encoding="utf-8")


def load_json_fixture(
    category: str, name: str, scenario: str = _DEFAULT_SCENARIO
) -> dict[str, Any]:
    """Load and parse a JSON fixture file (e.g. one of the fake `issues/*.json`)."""
    parsed: dict[str, Any] = json.loads(load_fixture(category, name, scenario))
    return parsed
