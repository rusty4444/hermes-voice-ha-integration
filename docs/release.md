# Release process

This repository ships three installation surfaces:

| Surface | Source | Release expectation |
|---|---|---|
| Home Assistant custom integration | `custom_components/hermes/` | Installed by HACS/manual copy from the GitHub release/tag. |
| Hermes plugins | `plugins/home_assistant/`, `plugins/voice_stack/` | Included in the Python wheel and source distribution. |
| Home Assistant add-on scaffold | `addon/` | Included in the source distribution and GitHub tag; treated as an early scaffold until add-on CI is expanded. |

The Python wheel is intentionally plugin-focused. The source distribution and GitHub tag contain the full bundle, including the Home Assistant custom component, add-on scaffold, docs, and skills.

## v0.0.18 release notes (2026-10-27)

- Create the optional insecure TLS context in HA's executor without changing the existing verification defaults ([#56](https://github.com/rusty4444/hermes-voice-ha-integration/pull/56)).
- Match opt-in local intents after removing only known Whisper non-speech annotations. Keep real speech, cancellations and multi-command transcripts intact for Hermes, and keep local processing disabled by default ([#57](https://github.com/rusty4444/hermes-voice-ha-integration/pull/57)).
- Keep the Python package, HACS integration, add-on scaffold, both Hermes plugin manifests, lockfile and version assertions aligned at 0.0.18.
- Thanks to Joel Silva ([@byjaps](https://github.com/byjaps)) for both runtime changes.

### Upgrade and reporter confirmation

Update the HA integration through HACS or manual copy, reinstall the Hermes-side plugins using the v0.0.18 pip command in the README, and restart Home Assistant and the Hermes process owning the receiver port. On the multiplexed installation reported in #49 that process was `hermes dashboard`, not the gateway. Updating HACS alone does not replace the Hermes-side plugins.

Issue #49 was confirmed resolved on v0.0.17 and closed after reporter acceptance; that evidence is not a live acceptance test for the new local-intent changes. Other reporter-dependent issues remain open. Local automated tests use mocked HA objects and loopback WebSocket clients; they do not establish live Home Assistant or end-to-end voice compatibility. Edge TTS requires an external service, and the add-on remains an early scaffold. Panel HUD markers proposed in #58 are not implemented by this release.

## Maintainer checklist

1. Update code and tests on a feature branch.
2. Update `CHANGELOG.md` with the next version.
3. Sync version metadata in:
   - `pyproject.toml`
   - `custom_components/hermes/manifest.json`
   - `addon/config.yaml`
   - `plugins/home_assistant/plugin.yaml`
   - `plugins/voice_stack/plugin.yaml`
   - `uv.lock` and the version assertions in `tests/test_plugin.py`
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

7. Wait for tag CI to pass, download its `release-dist` artifact, and create a GitHub release with the wheel, source distribution and release notes. Tag pushes do not create a GitHub release: the repository has no automated release-publishing workflow.
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

The workflow tests Python 3.11 and 3.12. On a `v*` tag, only the Python 3.12 job uploads `dist/*` as the `release-dist` Actions artifact. CI has read-only repository contents permissions and does not publish a GitHub release or upload assets to one. The maintainer must publish the release and attach the artifacts after verifying tag CI.
