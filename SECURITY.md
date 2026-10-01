# Security policy

## Supported version

Security fixes target the latest tagged release and the `main` branch.

## Reporting a vulnerability

Do not open a public issue for a vulnerability. Use GitHub's **Security → Report a vulnerability** flow for this repository, or privately contact the maintainer through the GitHub profile at <https://github.com/DailenG>.

Include:

- affected version and Omarchy version;
- reproduction steps;
- impact and required local permissions;
- relevant QML, Python, or shell paths;
- a proposed mitigation, if known.

You should receive an acknowledgment within seven days. Coordinated disclosure is preferred.

## Trust boundary

Omarcharium is an unsandboxed Omarchy shell plugin and runs with the current user's permissions. Its intended boundaries are deliberately narrow:

- no `sudo`, `pkexec`, package-manager, or installer execution;
- no runtime network access, remote assets, analytics, or data collection;
- no secrets or credentials read, stored, or transmitted;
- no writes to `/usr/share/omarchy/`;
- configuration only under a mode `0700` `~/.config/omarcharium/`, with renderer input capped at 256 KiB;
- selected backdrop images are local read-only inputs, copied at most 32 MiB into a private snapshot before bounded 24-megapixel decoding with an explicit JPEG, PNG, GIF, BMP, or WebP decoder; the QML preview loads only the derived PNG;
- derived backdrop PNGs are mode `0600`, limited to 16 files and 128 MiB under a mode `0700` `~/.cache/omarcharium/`;
- owned integration state only under a mode `0700` `~/.local/state/omarcharium/`, matching Omarchy's `$HOME/.local/state` toggle location;
- a no-follow mode `0600` audio lock under `$XDG_RUNTIME_DIR/omarcharium/`, with a private cache fallback when the runtime directory is unavailable;
- external processes limited to documented Omarchy, Hyprland, terminal, PipeWire, ImageMagick, and POSIX tools.

The idle helper serializes ownership changes and writes the same unique marker to the stock `screensaver-off` toggle and its private ownership record. A stale ownership record is reclaimed only when no toggle exists. Automatic immersion is armed only after ownership is confirmed; pre-existing or replaced user toggles suppress it. Disable removes the toggle only while both regular files still match.

Backdrop paths are passed as direct process arguments, never interpolated into shell command strings. Selection/completion paths live under a per-invocation private temporary directory. ImageMagick is forced to the decoder selected by the validated suffix and uses pinned, bounded source bytes with explicit memory, map, disk, dimension, and wall-clock limits. The shell preview loads only the bounded derived PNG. Temporary and cached files use exclusive creation, ownership checks, no-follow locks, and private permissions.

The shell IPC endpoint is intentionally available to processes in the same user session. It starts, stops, or configures the screensaver and is not an authentication boundary. The fixed **Report Bug** link is the only runtime action that opens a network-capable application, and it occurs only after explicit user interaction.

## Security review record

Release 1.0.9 received a full repository security review on 2026-08-31 before Marketplace submission. The review covered every QML, Python, shell, workflow, manifest, static-site, configuration, test, and documentation file; all 12 pre-review commits were scanned for common credential formats.

Addressed findings:

| Severity | Area | Resolution |
|---|---|---|
| Moderate | Runtime and integration-state files could follow pre-positioned symlinks; path-only ownership could remove a replacement toggle | Added no-follow owned lock opens, private directories, matched ownership markers, replacement preservation, and regression tests |
| Moderate | Configuration, terminal dimensions, and the derived-image cache lacked complete storage or allocation ceilings | Added a 256 KiB configuration limit, 500 × 200 cell ceiling, and 16-file/128 MiB cache pruning |
| Low | Image decoding relied on ImageMagick's automatic format selection after suffix validation | Forced an allowlisted decoder and private temporary directory for every identify and conversion operation |
| Low | GitHub Actions used mutable major-version references | Pinned each action to a verified full commit SHA while retaining read-only workflow permissions |
| Low | The project site used inline JavaScript without a restrictive policy | Moved script logic to a same-origin file and added a deny-by-default Content Security Policy and no-referrer policy |

No embedded secret, runtime network request, privilege-escalation path, package installation hook, shell interpolation of user configuration, or unresolved known vulnerability was found. Residual risk is limited by the stated trust model: the plugin is not sandboxed, supported local images are decoded by the system ImageMagick installation, and same-user processes can invoke the documented shell IPC actions.
