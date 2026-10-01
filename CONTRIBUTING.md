# Contributing to Omarcharium

Thank you for helping this reef evolve. Contributions should preserve three invariants: no privileged installation, no network dependency at runtime, and no regression to Omarchy's lock or idle behavior.

## Development environment

Use an up-to-date Omarchy Quattro installation with Python 3.11+, Quickshell, PipeWire tools, and one of Omarchy's supported terminal emulators.

```sh
git clone <repository-url>
cd omarcharium
omarchy plugin validate .
python3 -m unittest discover -s tests -v
bash -n scripts/launch-aquarium scripts/idle-integration scripts/select-backdrop
```

For a live development copy:

Stage newly added runtime files before this sync; untracked files are intentionally excluded. The explicit payload omits checkout metadata, tests, documentation, and developer-only files. Extend the path list when adding new runtime files:

```sh
PLUGIN_ID=dailen.omarcharium
PLUGIN_DIR="$HOME/.config/omarchy/plugins/$PLUGIN_ID"
mkdir -p "$PLUGIN_DIR"
git ls-files -z -- manifest.json Service.qml Config.qml defaults.json species.json assets/ scripts/ \
  | tar --create --file=- --null --verbatim-files-from --files-from=- \
  | tar --extract --file=- --directory="$PLUGIN_DIR"
omarchy plugin enable "$PLUGIN_ID"
omarchy restart shell
```

User plugin files usually hot-reload, but an already instantiated control-room overlay can retain its previous QML across a rescan. Restart the shell after copying runtime files before judging UI behavior.

## Change guidelines

### Renderer

- Keep every sprite glyph one terminal cell wide.
- Preserve deterministic `--snapshot` output when given a seed.
- Bound configured populations and frame work.
- Avoid per-frame subprocesses, file reads, or unbounded collections.
- Preserve the 256 KiB configuration and 500 × 200 cell allocation ceilings.
- Keep keyboard, click, and pointer-motion dismissal intact.

### Audio

- Keep audio optional and off by default.
- Use the single-process runtime lock; multi-monitor audio must never multiply.
- Verify the raw PCM path with `python3 scripts/aquarium.py --audio-test 3`.
- Do not add bundled recordings, codecs, Python packages, or network access.
- Keep lock files no-follow, user-owned, mode `0600`, and inside private directories.

### Omarchy integration

- Never modify `/usr/share/omarchy/`.
- Use the `org.omarchy.screensaver` application class so the first-party idle service can observe the windows.
- Preserve an existing user-owned `screensaver-off` toggle.
- Removing or disabling the plugin must release only state owned by Omarcharium.
- Treat the matched toggle and ownership markers as one ownership proof; never remove mismatched or replaced state.

### QML

- Follow the current Omarchy Quattro plugin contract.
- Keep `manifest.json`, `Service.qml`, and `Config.qml` IDs identical.
- Exercise the actual control-room surface; QML lint alone is not visual verification.
- Keep controls usable by keyboard as well as pointer.

## Tests and validation

Before opening a pull request:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/aquarium.py --snapshot --width 100 --height 30 --seed 7 >/dev/null
python3 scripts/aquarium.py --check-config >/dev/null
bash -n scripts/launch-aquarium scripts/idle-integration scripts/select-backdrop
omarchy plugin validate .
/usr/lib/qt6/bin/qmllint -I "$OMARCHY_PATH/shell" Service.qml Config.qml
```

`qmllint` currently emits Quickshell metadata warnings for `PanelWindow` and `QProcess::ExitStatus`; warnings are acceptable when it exits successfully and the live surface is verified. New warnings are not.

## Pull requests

Keep each pull request focused. Include:

- the observable problem and design decision;
- screenshots or a recording for visual changes;
- terminal output for renderer or audio changes;
- exact verification commands and results;
- documentation updates when configuration or behavior changes.

By contributing, you agree that your contribution is licensed under the MIT License.
