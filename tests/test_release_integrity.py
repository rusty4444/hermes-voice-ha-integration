"""Release and packaging integrity tests."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_release_integrity.py"

spec = importlib.util.spec_from_file_location("check_release_integrity", SCRIPT_PATH)
assert spec and spec.loader
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)


def test_all_release_versions_match_pyproject() -> None:
    assert release_check.check_versions() == []


def test_changelog_and_readme_reference_current_version() -> None:
    assert release_check.check_docs() == []


def test_required_hacs_component_and_addon_files_exist_and_parse() -> None:
    assert release_check.check_required_files() == []


def test_runtime_translation_file_matches_strings_json() -> None:
    assert release_check.check_translations() == []


def test_release_integrity_script_passes_without_artifacts() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--no-artifacts"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_release_artifacts_contain_expected_install_targets() -> None:
    subprocess.run([sys.executable, "-m", "build", "--sdist", "--wheel"], cwd=ROOT, check=True)
    assert release_check.check_artifacts() == []
