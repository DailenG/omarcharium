# Architecture

Omarcharium deliberately separates shell integration from the animation process. The Omarchy shell remains long-lived and lightweight; terminal rendering and audio exist only during an immersion.

```mermaid
flowchart LR
    Tray[StatusNotifierItem] --> Service[Service.qml]
    Service --> Config[Config.qml overlay]
    Service --> Idle[Quickshell IdleMonitor]
    Config --> JSON[~/.config/omarcharium/config.json]
    Idle --> Launcher[scripts/launch-aquarium]
    Config --> Launcher
    Launcher --> H[Hyprland monitor loop]
    H --> T1[Terminal monitor 1]
    H --> T2[Terminal monitor N]
    T1 --> Renderer[aquarium.py]
    T2 --> Renderer
    Renderer --> Lock[$XDG_RUNTIME_DIR audio lock]
    Lock --> PipeWire[pw-cat raw stereo PCM]
    H --> OmarchyIdle[First-party idle and lock service]
```

## Plugin lifecycle

`manifest.json` declares two entry points under one namespaced plugin ID:

- `service`: always loaded while the plugin is enabled;
- `overlay`: loaded by the shell when the control room is summoned.

`Service.qml` owns the tray item, IPC surface, and idle monitor. It launches the renderer rather than embedding animation work in the shared Quickshell process.

## Control room and persistence

`Config.qml` reads packaged defaults and the species catalog, normalizes user input, and atomically writes JSON under `~/.config/omarcharium/`. Every mutation creates a fresh QML object before assignment; this avoids silent change-notification loss from mutating nested `var` objects in place. Its image preview loads only the renderer's bounded cached PNG, never the original selected file.

The Python renderer independently normalizes the same public configuration contract. A malformed or partially written user file therefore falls back safely without preventing the screensaver from opening.

## Renderer

`OceanScene` renders a fixed layer stack:

1. background source (Plain Depth, Pelagic Field, or Custom Image);
2. optional pelagic current, scanline, and particle effects;
3. water and habitat;
4. fish;
5. local status display.

Backdrop effects are independent from the source so the same bounded terminal-native treatment can compose over built-in and user-selected sources. Each frame then advances positions from monotonic time, wraps entities at scene boundaries, paints into a cell buffer, emits ANSI truecolor only when the active foreground color changes, and erases the unpainted remainder of every row.

For **Custom Image**, `RasterBackdrop` canonicalizes a local allowlisted image, opens it once, and copies at most 32 MiB into a private snapshot. ImageMagick identifies and converts those same pinned bytes under memory, map, disk, 24-megapixel, and timeout bounds. A global no-follow cache lock serializes conversion. The cache key includes the snapshot's content hash, fit, and dimming; mode-`0600` outputs are pruned to 16 files and 128 MiB. The control-room preview reads the same bounded cached PNG after the configuration save completes. Ghostty and Kitty receive it through a negative-z Kitty graphics placement; resize sends a new placement without decoding again. Alacritty and Foot retain terminal-native layers and show a plain-depth fallback notice when the status display is enabled.

Sprites contain only single-cell glyphs. A mirror translation reverses direction without maintaining duplicate left-facing art. `--seed` makes snapshots deterministic for tests and visual debugging.
The terminal enters an alternate screen, hides the cursor, and enables SGR any-motion mouse reporting. A bounded input decoder distinguishes pointer motion from clicks and keyboard bytes, including fragmented reports. Cleanup restores every terminal mode on normal exit or signal. Accepted dismissal input closes all monitor instances through the standard Omarchy screensaver class.

## Multi-monitor and lock integration

`scripts/launch-aquarium` follows Omarchy's first-party screensaver launch pattern:

- remembers the focused monitor;
- opens the Hyprland event socket before launching;
- focuses each monitor and dispatches one supported terminal;
- waits for its `org.omarchy.screensaver` window before advancing;
- restores the original monitor focus.

The first-party idle service still owns locking. Omarcharium uses the same configured screensaver timeout and standard window class, so Omarchy observes active screensaver windows and preserves the configured lock deadline.

To suppress only the stock visualizer, `scripts/idle-integration` creates Omarchy's `screensaver-off` toggle when absent and records ownership separately. It reconciles a stale ownership record only when the toggle is absent, never claims an existing foreign toggle, and removes only matching owned state. Omarchy's toggle and Keep Awake paths live under `$HOME/.local/state` even when `XDG_STATE_HOME` differs. Automatic immersion is armed only after owned suppression is confirmed; a user-owned toggle disables automatic immersion, while manual launch remains available.

## Audio

Every renderer may request ambience, but `AmbientAudio` takes a non-blocking no-follow `flock` on a mode-`0600` regular file. Only one monitor becomes the audio leader. The lock lives in a mode-`0700` `$XDG_RUNTIME_DIR/omarcharium/` directory, or a private cache fallback if no absolute runtime directory is available. Audio streams generated signed 16-bit stereo PCM at 24 kHz to `pw-cat --raw`; no sample assets or codecs are involved.

The synthesis provides independently toggled continuous water motion and sparse frequency-rising bubble envelopes. `--audio-test` adds three diagnostic tones and verifies that `pw-cat` remains alive before reporting success.

| Resource | Access |
|---|---|
| Plugin source | Read-only at runtime |
| `~/.config/omarcharium/config.json` | Atomic user configuration read/write; directory mode `0700`; renderer input capped at 256 KiB |
| Selected backdrop image | Local read-only allowlisted input; copied into a private bounded snapshot before identifying or converting; 32 MiB and 24 megapixel limits |
| `~/.cache/omarcharium/` | Private derived backdrop PNGs for both renderer and control-room preview, global no-follow cache lock, 16-file/128 MiB ceiling |
| `~/.local/state/omarcharium/` | Private matched toggle ownership marker |
| `$XDG_RUNTIME_DIR/omarcharium/audio.lock` | Private no-follow ephemeral audio leadership lock |
| `/usr/share/omarchy/` | Read-only terminal defaults; never modified |
| Network | No runtime requests; a fixed bug-report URL opens only after user action |
| Privilege escalation | Never used |
