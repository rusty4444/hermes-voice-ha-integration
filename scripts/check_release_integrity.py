#!/usr/bin/env python3
"""Release integrity checks for hermes-voice-ha-integration.

The project ships several installation surfaces (HACS custom component,
Hermes plugins, Home Assistant add-on scaffold, and Python package artifacts).
This script keeps release metadata and required files in sync.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - dev extras install PyYAML
    yaml = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

VERSION_FILES = {
    "pyproject.toml": ("toml", ("project", "version")),
    "custom_components/hermes/manifest.json": ("json", ("version",)),
    "addon/config.yaml": ("yaml", ("version",)),
    "plugins/home_assistant/plugin.yaml": ("yaml", ("version",)),
    "plugins/voice_stack/plugin.yaml": ("yaml", ("version",)),
}

REQUIRED_FILES = [
    "hacs.json",
    "custom_components/hermes/__init__.py",
    "custom_components/hermes/config_flow.py",
    "custom_components/hermes/const.py",
    "custom_components/hermes/frontend.py",
    "custom_components/hermes/hacsfiles/hermes_action_bar.js",
    "custom_components/hermes/manifest.json",
    "custom_components/hermes/services.yaml",
    "custom_components/hermes/strings.json",
    "custom_components/hermes/translations/en.json",
    "custom_components/hermes/brand/icon.png",
    "custom_components/hermes/brand/icon@2x.png",
    "custom_components/hermes/brand/logo.png",
    "custom_components/hermes/brand/logo@2x.png",
    "addon/config.yaml",
    "addon/build.yaml",
    "addon/Dockerfile",
    "addon/run.sh",
    "plugins/home_assistant/plugin.yaml",
    "plugins/voice_stack/plugin.yaml",
    "skills/homescript/SKILL.md",
]

WHEEL_REQUIRED = [
    "plugins/home_assistant/plugin.yaml",
    "plugins/home_assistant/README.md",
    "plugins/voice_stack/plugin.yaml",
    "plugins/voice_stack/README.md",
]

SDIST_REQUIRED = REQUIRED_FILES + ["README.md", "CHANGELOG.md", "pyproject.toml"]


def _load_structured(path: str) -> object:
    full = ROOT / path
    suffix = full.suffix.lower()
    if suffix == ".json":
        return json.loads(full.read_text())
    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise AssertionError("PyYAML is required to parse YAML release metadata")
        return yaml.safe_load(full.read_text())
    if suffix == ".toml":
        return tomllib.loads(full.read_text())
    raise AssertionError(f"Unsupported structured file: {path}")


def _get_path(data: object, keys: tuple[str, ...]) -> object:
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise AssertionError(f"Missing key {'.'.join(keys)}")
        current = current[key]
    return current


def canonical_version() -> str:
    data = _load_structured("pyproject.toml")
    version = _get_path(data, ("project", "version"))
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise AssertionError(f"Invalid pyproject version: {version!r}")
    return version


def check_versions(tag: str | None = None) -> list[str]:
    errors: list[str] = []
    expected = canonical_version()
    for rel_path, (_kind, keys) in VERSION_FILES.items():
        try:
            value = _get_path(_load_structured(rel_path), keys)
        except Exception as exc:  # noqa: BLE001 - aggregate all errors
            errors.append(f"{rel_path}: cannot read version: {exc}")
            continue
        if value != expected:
            errors.append(f"{rel_path}: version {value!r} != pyproject {expected!r}")
    if tag:
        clean_tag = tag[1:] if tag.startswith("v") else tag
        if clean_tag != expected:
            errors.append(f"tag {tag!r} does not match pyproject version {expected!r}")
    return errors


def check_docs() -> list[str]:
    version = canonical_version()
    errors: list[str] = []
    changelog = (ROOT / "CHANGELOG.md").read_text()
    if f"## [{version}]" not in changelog:
        errors.append(f"CHANGELOG.md missing top-level entry for {version}")
    readme = (ROOT / "README.md").read_text()
    if f"v{version}" not in readme:
        errors.append(f"README.md missing release reference v{version}")
    return errors


def check_required_files() -> list[str]:
    errors: list[str] = []
    for rel_path in REQUIRED_FILES:
        if not (ROOT / rel_path).exists():
            errors.append(f"missing required file: {rel_path}")
    for rel_path in ("hacs.json", "custom_components/hermes/manifest.json", "custom_components/hermes/strings.json", "custom_components/hermes/translations/en.json"):
        try:
            _load_structured(rel_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel_path}: parse failed: {exc}")
    for rel_path in ("addon/config.yaml", "addon/build.yaml", "plugins/home_assistant/plugin.yaml", "plugins/voice_stack/plugin.yaml"):
        try:
            _load_structured(rel_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel_path}: parse failed: {exc}")
    return errors


def check_translations() -> list[str]:
    strings = _load_structured("custom_components/hermes/strings.json")
    translations = _load_structured("custom_components/hermes/translations/en.json")
    if strings != translations:
        return ["custom_components/hermes/translations/en.json must match strings.json"]
    return []


def _normalise_sdist_name(name: str) -> str:
    parts = name.split("/", 1)
    return parts[1] if len(parts) == 2 else name


def check_artifacts() -> list[str]:
    errors: list[str] = []
    dist = ROOT / "dist"
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if not wheels or not sdists:
        return ["dist/ must contain freshly built wheel and sdist artifacts"]

    wheel = wheels[-1]
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
    for rel_path in WHEEL_REQUIRED:
        if rel_path not in names:
            errors.append(f"{wheel.name}: missing plugin runtime file {rel_path}")

    sdist = sdists[-1]
    with tarfile.open(sdist) as tf:
        names = {_normalise_sdist_name(n) for n in tf.getnames()}
    for rel_path in SDIST_REQUIRED:
        if rel_path not in names:
            errors.append(f"{sdist.name}: missing bundle file {rel_path}")
    return errors


def run_checks(tag: str | None = None, artifacts: bool = True) -> list[str]:
    errors: list[str] = []
    errors.extend(check_versions(tag))
    errors.extend(check_docs())
    errors.extend(check_required_files())
    errors.extend(check_translations())
    if artifacts:
        errors.extend(check_artifacts())
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Release tag to compare with the canonical version, e.g. v0.1.0")
    parser.add_argument("--no-artifacts", action="store_true", help="Skip dist/ wheel+sdist content checks")
    args = parser.parse_args()

    errors = run_checks(tag=args.tag, artifacts=not args.no_artifacts)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"release integrity ok: v{canonical_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
