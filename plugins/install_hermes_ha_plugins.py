"""Install the Hermes Home Assistant plugins from the Python package.

This module backs the ``hermes-ha-install-plugins`` console command. It copies
this package's plugin directories into a Hermes Agent profile, replacing any
previous copies so removed files do not linger after upgrades.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

PLUGIN_NAMES = ("home_assistant", "voice_stack")
DEFAULT_PROFILE = Path.home() / ".hermes" / "hermes-agent"


def _package_plugins_dir() -> Path:
    return Path(__file__).resolve().parent


def _target_plugins_dir(profile: Path) -> Path:
    return profile.expanduser().resolve() / "plugins"


def install_plugins(profile: Path = DEFAULT_PROFILE, *, dry_run: bool = False) -> list[tuple[Path, Path]]:
    """Install bundled plugin directories into ``profile/plugins``.

    Existing plugin directories with the same names are removed before copying.
    That replacement behaviour is intentional: it prevents stale files from
    older releases remaining in a user's Hermes plugin directory.
    """

    source_root = _package_plugins_dir()
    target_root = _target_plugins_dir(profile)
    operations: list[tuple[Path, Path]] = []

    for plugin_name in PLUGIN_NAMES:
        source = source_root / plugin_name
        if not source.is_dir():
            raise FileNotFoundError(f"Packaged plugin directory not found: {source}")
        operations.append((source, target_root / plugin_name))

    if dry_run:
        return operations

    target_root.mkdir(parents=True, exist_ok=True)
    for source, target in operations:
        if target.exists():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
        shutil.copytree(source, target, ignore=ignore)

    return operations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install Hermes Home Assistant plugins into a Hermes Agent profile.",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(os.environ.get("HERMES_PROFILE_DIR", DEFAULT_PROFILE)),
        help="Hermes Agent profile directory containing the plugins/ folder "
        "(default: %(default)s).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without writing files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        operations = install_plugins(args.profile, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 - CLI should present concise failure
        print(f"error: {exc}", file=sys.stderr)
        return 1

    action = "Would install" if args.dry_run else "Installed"
    for source, target in operations:
        print(f"{action} {source.name} -> {target}")
    if not args.dry_run:
        print("Restart Hermes Agent to load updated plugins.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
