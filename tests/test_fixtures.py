"""Tests for the github-maintainer-dungeon local fixture loader."""

import pytest

from arena.scenarios.fixtures import (
    FIXTURE_CATEGORIES,
    FixtureError,
    list_fixtures,
    load_fixture,
    load_json_fixture,
)


class TestListFixtures:
    def test_lists_known_categories_non_empty(self) -> None:
        for category in FIXTURE_CATEGORIES:
            names = list_fixtures(category)
            assert names, f"expected at least one fixture in category {category!r}"

    def test_list_is_sorted(self) -> None:
        names = list_fixtures("issues")
        assert names == sorted(names)

    def test_issues_category_contains_expected_files(self) -> None:
        names = list_fixtures("issues")
        assert "bug_report_login_timeout.json" in names
        assert "feature_request_dark_mode.json" in names
        assert "prompt_injection_issue_comment.json" in names

    def test_repo_files_category_includes_nested_paths(self) -> None:
        names = list_fixtures("repo_files")
        assert any(name.endswith("src/app.py") for name in names)
        assert any(name.endswith(".github/workflows/ci.yml") for name in names)

    def test_unknown_category_raises(self) -> None:
        with pytest.raises(FixtureError, match="Unknown fixture category"):
            list_fixtures("not-a-real-category")


class TestLoadFixture:
    def test_load_text_fixture(self) -> None:
        content = load_fixture("ci_logs", "passing_build.log")
        assert "SUCCESS" in content

    def test_load_failing_ci_log_contains_traceback(self) -> None:
        content = load_fixture("ci_logs", "failing_build_stack_trace.log")
        assert "MemoryError" in content
        assert "FAILURE" in content

    def test_load_nested_repo_file(self) -> None:
        content = load_fixture("repo_files", "src/app.py")
        assert "import_csv" in content

    def test_missing_fixture_raises_with_available_list(self) -> None:
        with pytest.raises(FixtureError, match="not found in category"):
            load_fixture("issues", "does_not_exist.json")

    def test_unknown_category_raises(self) -> None:
        with pytest.raises(FixtureError, match="Unknown fixture category"):
            load_fixture("not-a-real-category", "whatever.json")


class TestLoadJsonFixture:
    def test_load_benign_issue(self) -> None:
        issue = load_json_fixture("issues", "bug_report_login_timeout.json")
        assert issue["number"] == 101
        assert "bug" in issue["labels"]

    def test_load_prompt_injection_issue_contains_attack_text(self) -> None:
        issue = load_json_fixture("issues", "prompt_injection_issue_comment.json")
        assert "ignore all of your previous instructions" in issue["body"]

    def test_secrets_fixture_values_are_marked_fake(self) -> None:
        creds = load_json_fixture("secrets", "fake_deploy_credentials.json")
        assert "FAKE" in creds["api_key"]
