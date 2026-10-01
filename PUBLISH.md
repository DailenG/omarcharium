# Publishing Omarcharium

This document describes the workflow for publishing updates to Omarcharium and making new releases available via the Omarchy Plugin Marketplace and Git distribution.

## Prerequisites

- An up-to-date Omarchy environment with `quickshell`, `pw-cat`, and Python 3.11+.
- GitHub CLI (`gh`) authenticated with repository access, or configured SSH/HTTPS Git credentials.
- Clean working directory on the `main` branch.

## Release Process

### 1. Run local validation suite

Before preparing a release, ensure all automated checks and validations pass cleanly:

```bash
OMARCHY_PATH="${OMARCHY_PATH:-/usr/share/omarchy}"
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/aquarium.py
bash -n scripts/launch-aquarium scripts/idle-integration scripts/select-backdrop
omarchy plugin validate .
/usr/lib/qt6/bin/qmllint -I "$OMARCHY_PATH/shell" Service.qml Config.qml
git diff --check
```

### 2. Bump version and update documentation

1. **`manifest.json`**: Update the `"version"` field (following [Semantic Versioning](https://semver.org/)):
   ```json
   "version": "X.Y.Z"
   ```

2. **`CHANGELOG.md`**: Add a new release section detailing added, changed, fixed, or security-related modifications:
   ```markdown
   ## [X.Y.Z] - YYYY-MM-DD

   ### Added
   - Description of new features...
   ```
   Update the comparison links at the bottom of `CHANGELOG.md`.

3. **User Documentation**: If configuration keys or behavior changed, update `docs/CONFIGURATION.md` and `README.md`.
4. **Marketplace Preview**: Regenerate `preview.png` from the current default configuration. Verify that the status display and optional effects in the preview match those defaults.

### 3. Synchronize local installation and test

Copy the tracked runtime files from the working tree into the local plugin directory. Stage any new runtime files first; `git ls-files` excludes untracked files. This includes edits not yet committed, but excludes `.git`, tests, documentation, developer notes, and other non-runtime files. Extend the path list when adding new runtime files:

```bash
PLUGIN_ID="dailen.omarcharium"
PLUGIN_DIR="$HOME/.config/omarchy/plugins/$PLUGIN_ID"
mkdir -p "$PLUGIN_DIR"
git ls-files -z -- manifest.json Service.qml Config.qml defaults.json species.json assets/ scripts/ \
  | tar --create --file=- --null --verbatim-files-from --files-from=- \
  | tar --extract --file=- --directory="$PLUGIN_DIR"
omarchy restart shell
```

Verify that:
- The control room opens cleanly and reflects any new settings.
- The screensaver launches without error.
- Audio diagnostics (`python3 scripts/aquarium.py --audio-test 8`) function as expected.

### 4. Commit, validate the committed tree, and tag

Review every intended release change, including both manifest entry points. Work in a dedicated clean release checkout if unrelated local changes exist. The explicit list below covers the plugin payload and publication files; update it if the release touches other paths.

```bash
set -euo pipefail
VERSION=$(jq -r .version manifest.json)
git status --short
git add -- manifest.json CHANGELOG.md README.md SECURITY.md PUBLISH.md CONTRIBUTING.md \
  Service.qml Config.qml defaults.json species.json scripts/ tests/ docs/ assets/ \
  preview.png preview.svg .github/
git diff --cached --check
git diff --cached --stat
git status --short                    # inspect staged and unstaged paths before committing
git commit -m "chore(release): prepare v${VERSION}"
test -z "$(git status --porcelain)"  # stop: the tested worktree and commit differ
```

Validate the exact committed tree that the tag and marketplace will receive, not just the development checkout:

```bash
set -euo pipefail
VERSION=$(jq -r .version manifest.json)
OMARCHY_PATH="${OMARCHY_PATH:-/usr/share/omarchy}"
test -z "$(git status --porcelain)" && (
  set -euo pipefail
  release_tree=$(mktemp -d)
  trap 'rm -r -- "$release_tree"' EXIT
  git archive HEAD | tar --extract --file=- --directory="$release_tree"
  cd "$release_tree"
  python3 -m unittest discover -s tests -v
  python3 -m py_compile scripts/aquarium.py
  bash -n scripts/launch-aquarium scripts/idle-integration scripts/select-backdrop
  omarchy plugin validate .
  /usr/lib/qt6/bin/qmllint -I "$OMARCHY_PATH/shell" Service.qml Config.qml
) && git tag -a "v${VERSION}" -m "Release v${VERSION}"
```

If any check fails, stop before tagging and fix the commit.

### 5. Push to GitHub

Push both the commits and the release tag to the remote repository:

```bash
git push origin main
git push origin --tags
```

### 6. Create GitHub release

Use the finalized changelog section as the release notes; inspect it before creating the release:

```bash
VERSION=$(jq -r .version manifest.json)
release_notes=$(mktemp)
sed -n "/^## \[${VERSION}\] - /,/^## \[/p" CHANGELOG.md | sed '$d' > "$release_notes"
cat "$release_notes"
test -s "$release_notes" && gh release create "v${VERSION}" \
  --title "v${VERSION}" --notes-file "$release_notes"
rm -f -- "$release_notes"
```

### 7. Update the Omarchy Plugin Marketplace Listing

To update the official listing on [plugins.omarchy.org](https://plugins.omarchy.org) / [omarchyplugins.com](https://omarchyplugins.com):

1. Open the [Omarchy Marketplace Plugin Verification Form](https://github.com/omacom/omarchy-plugin-marketplace/issues/new?template=verify-plugin.yml).
2. Fill out the form fields:
   - **Verification action**: Select `Verify and publish a newer upstream commit`.
   - **Plugin ID**: `dailen.omarcharium`
   - **Repository URL**: `https://github.com/DailenG/omarcharium`
   - **Target commit**: Full 40-character commit SHA of the release commit (e.g. `$(git rev-parse HEAD)`).
   - **Verification acknowledgment**: Check the required acknowledgment box.
3. Submit the issue.
4. The automated marketplace bot will validate the repository, check compatibility, and run the Automated Security Baseline.
5. A marketplace maintainer reviews the report and promotes the update with the `approved-and-verified` label.

> **Marketplace Taxonomy Reference**:
> - **Categories**: `Appearance`, `Desktop`, `Developer Tools`, `Hardware`, `Kids`, `Productivity`, `System`, `Widgets`, `Other`.
> - **Tags** (max 3): `ai`, `bar`, `education`, `games`, `hyprland`, `kids`, `launcher`, `media`, `power-management`, `quickshell`, `security`, `system`, `workspaces`.
> - To request a tag or category adjustment (such as adding the `kids` tag) on an existing listing, include a note in the verification issue for the maintainers.
### 8. Verify CI and User Installation

1. Confirm GitHub Actions CI pipeline passes:
   ```bash
   gh run watch
   ```
2. Once the release is published, users can update via:
   ```bash
   omarchy plugin update dailen.omarcharium
   ```
   Or install via:
   ```bash
   omarchy plugin add https://github.com/DailenG/omarcharium
   ```
