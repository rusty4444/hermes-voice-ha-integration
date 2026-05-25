# Release process

This repository ships three installation surfaces:

| Surface | Source | Release expectation |
|---|---|---|
| Home Assistant custom integration | `custom_components/hermes/` | Installed by HACS/manual copy from the GitHub release/tag. |
| Hermes plugins | `plugins/home_assistant/`, `plugins/voice_stack/` | Included in the Python wheel and source distribution. |
| Home Assistant add-on scaffold | `addon/` | Included in the source distribution and GitHub tag; treated as an early scaffold until add-on CI is expanded. |

The Python wheel is intentionally plugin-focused. The source distribution and GitHub tag contain the full bundle, including the Home Assistant custom component, add-on scaffold, docs, and skills.

## Maintainer checklist

1. Update code and tests on a feature branch.
2. Update `CHANGELOG.md` with the next version.
3. Sync version metadata in:
   - `pyproject.toml`
   - `custom_components/hermes/manifest.json`
   - `addon/config.yaml`
   - `plugins/home_assistant/plugin.yaml`
   - `plugins/voice_stack/plugin.yaml`
   - README release line
4. Run local verification:

   ```bash
   python -m compileall -q custom_components plugins tests scripts
   python -m pytest -q
   python -m build --sdist --wheel
   python scripts/check_release_integrity.py
   ```

5. Open and merge the PR after CI is green.
6. Tag from `main`:

   ```bash
   git fetch --tags origin
   git checkout main
   git pull --ff-only origin main
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

7. Create a GitHub release with the built artifacts and release notes.
8. Verify the release:

   ```bash
   gh release view vX.Y.Z --json tagName,name,url,isDraft,isPrerelease,assets
   python scripts/check_release_integrity.py --tag vX.Y.Z
   ```

## CI gates

The CI workflow runs on pull requests, `main`, and version tags. It verifies:

- Python compilation
- pytest suite
- wheel/source distribution build
- metadata/version integrity
- tag/version match for `v*` tags
