"""Tests for the packaged Hermes plugin installer."""

from __future__ import annotations

from pathlib import Path

from plugins.install_hermes_ha_plugins import PLUGIN_NAMES, install_plugins


def test_install_plugins_replaces_existing_plugin_dirs(tmp_path: Path) -> None:
    profile = tmp_path / "hermes-agent"
    plugins_dir = profile / "plugins"

    stale_dir = plugins_dir / "home_assistant"
    stale_dir.mkdir(parents=True)
    (stale_dir / "stale_file.py").write_text("old")

    operations = install_plugins(profile)

    assert {target.name for _source, target in operations} == set(PLUGIN_NAMES)
    for plugin_name in PLUGIN_NAMES:
        target = plugins_dir / plugin_name
        assert target.is_dir()
        assert (target / "plugin.yaml").is_file()

    assert not (stale_dir / "stale_file.py").exists()


def test_install_plugins_dry_run_does_not_write(tmp_path: Path) -> None:
    profile = tmp_path / "hermes-agent"

    operations = install_plugins(profile, dry_run=True)

    assert len(operations) == len(PLUGIN_NAMES)
    assert not (profile / "plugins").exists()
