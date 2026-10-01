#!/usr/bin/env python3
"""Omarcharium: a terminal-native tropical aquarium for Omarchy.

The interactive path paints an ANSI true-colour scene until configured
keyboard or mouse input arrives. The snapshot and configuration modes are deterministic,
which keeps the renderer testable without a compositor or terminal emulator.
"""

from __future__ import annotations

import argparse
import base64
import copy
import fcntl
import hashlib
import json
import math
import os
import random
import select
import shutil
import signal
import stat
import struct
import subprocess
import sys
import termios
import threading
import time
import tempfile
import tty
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PLUGIN_DIR = Path(__file__).resolve().parent.parent
DEFAULTS_PATH = PLUGIN_DIR / "defaults.json"
SPECIES_PATH = PLUGIN_DIR / "species.json"
CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omarcharium" / "config.json"
MAX_CONFIG_BYTES = 256 * 1024
MAX_TERMINAL_COLUMNS = 500
MAX_TERMINAL_LINES = 200

RGB = tuple[int, int, int]

def mix_rgb(start: RGB, end: RGB, amount: float) -> RGB:
    amount = max(0.0, min(1.0, amount))
    return tuple(round(left + (right - left) * amount) for left, right in zip(start, end))

PALETTES: dict[str, dict[str, RGB]] = {
    "lagoon": {
        "background": (2, 18, 28), "water": (29, 120, 143), "caustic": (93, 230, 226),
        "sand": (180, 141, 86), "rock": (45, 82, 78), "kelp": (42, 167, 117),
        "coral": (255, 103, 126), "dim": (31, 79, 92), "text": (161, 241, 235),
    },
    "midnight": {
        "background": (1, 6, 18), "water": (24, 54, 111), "caustic": (95, 109, 232),
        "sand": (91, 81, 116), "rock": (39, 47, 82), "kelp": (29, 119, 119),
        "coral": (181, 80, 205), "dim": (31, 51, 94), "text": (147, 186, 255),
    },
    "coral": {
        "background": (21, 8, 20), "water": (138, 49, 93), "caustic": (255, 149, 111),
        "sand": (220, 151, 92), "rock": (91, 49, 68), "kelp": (103, 171, 113),
        "coral": (255, 82, 95), "dim": (95, 45, 76), "text": (255, 216, 175),
    },
    "phosphor": {
        "background": (0, 11, 8), "water": (20, 105, 66), "caustic": (99, 255, 169),
        "sand": (81, 149, 90), "rock": (30, 67, 47), "kelp": (49, 192, 91),
        "coral": (153, 255, 123), "dim": (22, 77, 48), "text": (155, 255, 189),
    },
}

FISH_COLOURS: dict[str, tuple[RGB, RGB, RGB]] = {
    "neon_tetra": ((52, 219, 255), (245, 76, 126), (157, 245, 255)),
    "clownfish": ((255, 132, 48), (255, 239, 191), (156, 54, 35)),
    "angelfish": ((242, 229, 175), (97, 208, 220), (147, 118, 94)),
    "discus": ((255, 92, 174), (80, 224, 211), (126, 52, 130)),
    "butterflyfish": ((255, 225, 70), (255, 250, 202), (44, 67, 79)),
    "royal_tang": ((65, 137, 255), (255, 227, 62), (20, 55, 138)),
    "betta": ((187, 93, 255), (64, 224, 239), (106, 43, 148)),
    "puffer": ((164, 232, 101), (255, 222, 90), (62, 104, 63)),
}

# Right-facing animation frames. Spaces are transparent; all glyphs are one
# terminal cell wide so geometry is stable under any monospace font.
SPRITES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "neon_tetra": (
        ("  __/=>", "<==_o_>"),
        ("  __/=>", "<~=_o_>"),
    ),
    "clownfish": (
        ("   .---.  ", "<==|o|==)>", "   '---'  "),
        ("  .----.  ", "<~=|o|==)>", "  '----'  "),
    ),
    "angelfish": (
        ("    /|   ", " __/ |   ", "<== o|)>", "   \\ |   ", "    \\|   "),
        ("    /|   ", "  _/ |   ", "<~= o|)>", " __\\ |   ", "    \\|   "),
    ),
    "discus": (
        ("  .-===-. ", "<=| o  |)>", "  '-===-' "),
        ("  .-===-. ", "<~| o  |)>", "  '-===-' "),
    ),
    "butterflyfish": (
        ("    /\\   ", "<==/##\\  ", "  |#o#|)>", "   \\##/  "),
        ("   _/\\   ", "<~=/##\\  ", "  |#o#|)>", "   \\##/  "),
    ),
    "royal_tang": (
        ("   __---. ", "<==  @  )>", "   '--__' "),
        ("   __---. ", "<~=  @  )>", "   '--__' "),
    ),
    "betta": (
        ("     __   ", "<~~~~_o\\)>", "  ~~  /  ", "   ~~/   "),
        ("    ___   ", "<~~~__o\\)>", "   ~~ /  ", "  ~~ /   "),
    ),
    "puffer": (
        ("  ^-^-^  ", "<= (o ) >", "  v-v-v  "),
        ("  ^-^-^  ", "<~ (o ) >", "  v-v-v  "),
    ),
}

MIRROR_TABLE = str.maketrans("<>/\\(){}[]", "><\\/)(}{][")


def mirror_sprite(lines: Iterable[str]) -> tuple[str, ...]:
    return tuple(line.translate(MIRROR_TABLE)[::-1] for line in lines)




def clamp_number(value: Any, low: float, high: float, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return max(low, min(high, number))


def read_json(path: Path, fallback: Any) -> Any:
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_CONFIG_BYTES + 1)
        if len(payload) > MAX_CONFIG_BYTES:
            return copy.deepcopy(fallback)
        return json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return copy.deepcopy(fallback)


def normalise_config(raw: Any) -> dict[str, Any]:
    defaults = read_json(DEFAULTS_PATH, {})
    incoming = raw if isinstance(raw, dict) else {}
    default_species = defaults.get("species", {})
    incoming_species = incoming.get("species", {})
    if not isinstance(incoming_species, dict):
        incoming_species = {}
    species: dict[str, int] = {}
    for key, fallback in default_species.items():
        species[key] = int(clamp_number(incoming_species.get(key), 0, 20, fallback))

    art = incoming.get("art", {})
    if not isinstance(art, dict):
        art = {}
    fallback_art = defaults.get("art", {})
    palette = str(art.get("palette", fallback_art.get("palette", "lagoon")))
    if palette not in PALETTES:
        palette = "lagoon"
    backdrop = incoming.get("backdrop", {})
    if not isinstance(backdrop, dict):
        backdrop = {}
    fallback_backdrop = defaults.get("backdrop", {})
    backdrop_source = str(backdrop.get("source", fallback_backdrop.get("source", "plain")))
    if backdrop_source not in {"plain", "pelagic", "image"}:
        backdrop_source = "plain"
    image_path = backdrop.get("imagePath", fallback_backdrop.get("imagePath", ""))
    image_path = image_path if isinstance(image_path, str) else ""
    fit_mode = str(backdrop.get("fitMode", fallback_backdrop.get("fitMode", "cover")))
    if fit_mode not in {"cover", "contain", "center"}:
        fit_mode = "cover"

    sound = incoming.get("sound", {})
    if not isinstance(sound, dict):
        sound = {}
    fallback_sound = defaults.get("sound", {})
    integration = incoming.get("integration", {})
    if not isinstance(integration, dict):
        integration = {}
    fallback_integration = defaults.get("integration", {})
    return {
        "schemaVersion": 1,
        "species": species,
        "art": {
            "palette": palette,
            "bubbleDensity": int(clamp_number(art.get("bubbleDensity"), 0, 100, fallback_art.get("bubbleDensity", 55))),
            "current": round(clamp_number(art.get("current"), 0.35, 1.8, fallback_art.get("current", 1.0)), 2),
            "showTelemetry": bool(art.get("showTelemetry", fallback_art.get("showTelemetry", False))),
            "reefDensity": int(clamp_number(
                (incoming.get("art", {}) if isinstance(incoming.get("art"), dict) else {}).get(
                    "reefDensity",
                    (incoming.get("art", {}) if isinstance(incoming.get("art"), dict) else {}).get("vegetationVolume", art.get("reefDensity", fallback_art.get("reefDensity", 50)))
                ),
                0, 100, fallback_art.get("reefDensity", 50),
            )),
        },
        "backdrop": {
            "source": backdrop_source,
            "imagePath": image_path,
            "fitMode": fit_mode,
            "dimming": int(clamp_number(
                backdrop.get("dimming"), 0, 90, fallback_backdrop.get("dimming", 45),
            )),
            "effectsEnabled": backdrop.get("effectsEnabled")
            if isinstance(backdrop.get("effectsEnabled"), bool)
            else bool(fallback_backdrop.get("effectsEnabled", False)),
            "effectIntensity": int(clamp_number(
                backdrop.get("effectIntensity"), 0, 100,
                fallback_backdrop.get("effectIntensity", 55),
            )),
        },
        "sound": {
            "enabled": bool(sound.get("enabled", fallback_sound.get("enabled", False))),
            "volume": int(clamp_number(sound.get("volume"), 0, 100, fallback_sound.get("volume", 24))),
            "water": bool(
                sound.get(
                    "water",
                    sound.get("waterFlow", sound.get("waterEnabled", fallback_sound.get("water", True))),
                )
            ),
            "bubbles": bool(
                sound.get(
                    "bubbles",
                    sound.get("bubblesEnabled", fallback_sound.get("bubbles", True)),
                )
            ),
        },
        "integration": {
            "idleEnabled": bool(integration.get("idleEnabled", fallback_integration.get("idleEnabled", True))),
            "exitOnPointerMotion": integration.get("exitOnPointerMotion")
            if isinstance(integration.get("exitOnPointerMotion"), bool)
            else bool(fallback_integration.get("exitOnPointerMotion", True)),
        },
    }


def load_config(path: Path) -> dict[str, Any]:
    return normalise_config(read_json(path, {}))

def clamp_dimensions(width: int, height: int) -> tuple[int, int]:
    return (
        max(40, min(MAX_TERMINAL_COLUMNS, width)),
        max(16, min(MAX_TERMINAL_LINES, height)),
    )


def ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise OSError(f"unsafe directory: {path}")
    path.chmod(0o700)


def open_lock_file(path: Path) -> Any:
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise OSError(f"unsafe lock file: {path}")
        os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "a+b")
    except Exception:
        os.close(descriptor)
        raise


def user_cache_home() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME", "")
    if configured and Path(configured).is_absolute():
        return Path(configured)
    return Path.home() / ".cache"


def runtime_directory() -> Path:
    configured = os.environ.get("XDG_RUNTIME_DIR", "")
    if configured and Path(configured).is_absolute():
        return Path(configured) / "omarcharium"
    return user_cache_home() / "omarcharium" / "runtime"


@dataclass(slots=True)
class Fish:
    species: str
    x: float
    base_y: float
    direction: int
    speed: float
    phase: float
    bob_rate: float
    bob_height: float
    frame_phase: float


@dataclass(slots=True)
class Bubble:
    x: float
    y: float
    speed: float
    drift: float
    size: int
    phase: float


@dataclass(slots=True)
class Mote:
    x: float
    y: float
    phase: float
    speed: float


class FrameBuffer:
    __slots__ = ("width", "height", "chars", "colours")

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.chars = [[" "] * width for _ in range(height)]
        self.colours: list[list[RGB | None]] = [[None] * width for _ in range(height)]

    def put(self, x: int, y: int, char: str, colour: RGB | None) -> None:
        if 0 <= x < self.width and 0 <= y < self.height and char:
            self.chars[y][x] = char[0]
            self.colours[y][x] = colour

    def text(self, x: int, y: int, text: str, colour: RGB | None) -> None:
        for offset, char in enumerate(text):
            self.put(x + offset, y, char, colour)

    def plain(self) -> str:
        return "\n".join("".join(row).rstrip() for row in self.chars)

    def ansi(self) -> str:
        output: list[str] = ["\x1b[H"]
        current: RGB | None = None
        for y, row in enumerate(self.chars):
            last = self.width - 1
            while last >= 0 and row[last] == " ":
                last -= 1
            for x in range(last + 1):
                colour = self.colours[y][x]
                if colour is not None and colour != current:
                    output.append(f"\x1b[38;2;{colour[0]};{colour[1]};{colour[2]}m")
                    current = colour
                output.append(row[x])
            output.append("\x1b[K")
            if y != self.height - 1:
                output.append("\n")
        output.append("\x1b[0m")
        return "".join(output)


class OceanScene:
    def __init__(self, width: int, height: int, config: dict[str, Any], seed: int) -> None:
        self.width, self.height = clamp_dimensions(width, height)
        self.config = config
        self.rng = random.Random(seed)
        self.elapsed = 0.0
        self.frame = 0
        self.fish: list[Fish] = []
        self.bubbles: list[Bubble] = []
        self.motes: list[Mote] = []
        self.backdrop_shades = tuple(
            mix_rgb(self.palette["background"], self.palette["water"], 0.07 + index * 0.025)
            for index in range(8)
        )
        self.backdrop_notice = ""
        self._populate()

    @property
    def palette(self) -> dict[str, RGB]:
        return PALETTES[self.config["art"]["palette"]]

    def _populate(self) -> None:
        self.fish.clear()
        for species, count in self.config["species"].items():
            if species not in SPRITES:
                continue
            for index in range(count):
                frame = SPRITES[species][0]
                depth_min = 5 + (index % 3)
                depth_max = max(depth_min + 1, self.height - len(frame) - 6)
                direction = self.rng.choice((-1, 1))
                base_speed = {
                    "neon_tetra": 8.0, "clownfish": 4.8, "angelfish": 2.4,
                    "discus": 2.9, "butterflyfish": 4.0, "royal_tang": 5.6,
                    "betta": 2.0, "puffer": 2.2,
                }.get(species, 3.5)
                self.fish.append(Fish(
                    species=species,
                    x=self.rng.uniform(-10, self.width + 10),
                    base_y=self.rng.uniform(depth_min, depth_max),
                    direction=direction,
                    speed=base_speed * self.rng.uniform(0.72, 1.28),
                    phase=self.rng.uniform(0, math.tau),
                    bob_rate=self.rng.uniform(0.45, 1.15),
                    bob_height=self.rng.uniform(0.35, 1.4),
                    frame_phase=self.rng.uniform(0, math.tau),
                ))

        density = self.config["art"]["bubbleDensity"]
        bubble_count = int((self.width * self.height) * density / 8500) + density // 12
        for _ in range(bubble_count):
            self.bubbles.append(self._new_bubble(self.rng.uniform(2, self.height - 3)))

        mote_count = max(10, self.width * self.height // 260)
        for _ in range(mote_count):
            self.motes.append(Mote(
                x=self.rng.uniform(0, self.width), y=self.rng.uniform(3, self.height - 4),
                phase=self.rng.uniform(0, math.tau), speed=self.rng.uniform(0.05, 0.24),
            ))

    def _new_bubble(self, y: float | None = None) -> Bubble:
        return Bubble(
            x=self.rng.uniform(2, self.width - 2),
            y=self.height - 3 if y is None else y,
            speed=self.rng.uniform(1.6, 4.8),
            drift=self.rng.uniform(0.3, 1.1),
            size=self.rng.choices((0, 1, 2), weights=(6, 3, 1))[0],
            phase=self.rng.uniform(0, math.tau),
        )

    def resize(self, width: int, height: int) -> None:
        width, height = clamp_dimensions(width, height)
        if width == self.width and height == self.height:
            return
        self.width = width
        self.height = height
        for fish in self.fish:
            fish.x %= self.width + 20
            fish.base_y = max(4, min(self.height - 8, fish.base_y))
        for bubble in self.bubbles:
            bubble.x %= self.width
            bubble.y = max(3, min(self.height - 3, bubble.y))

    def update(self, dt: float) -> None:
        dt = min(0.1, max(0.0, dt))
        self.elapsed += dt
        self.frame += 1
        current = self.config["art"]["current"]
        for fish in self.fish:
            fish.x += fish.direction * fish.speed * current * dt
            sprite_width = max(map(len, SPRITES[fish.species][0]))
            if fish.direction > 0 and fish.x > self.width + sprite_width:
                fish.x = -sprite_width - self.rng.uniform(0, self.width * 0.25)
                fish.base_y = self.rng.uniform(5, max(6, self.height - 9))
            elif fish.direction < 0 and fish.x < -sprite_width * 2:
                fish.x = self.width + self.rng.uniform(0, self.width * 0.25)
                fish.base_y = self.rng.uniform(5, max(6, self.height - 9))

        for bubble in self.bubbles:
            bubble.y -= bubble.speed * dt
            bubble.x += math.sin(self.elapsed * 1.7 + bubble.phase) * bubble.drift * dt
            if bubble.y < 3:
                replacement = self._new_bubble()
                bubble.x, bubble.y = replacement.x, replacement.y
                bubble.speed, bubble.drift = replacement.speed, replacement.drift
                bubble.size, bubble.phase = replacement.size, replacement.phase

        for mote in self.motes:
            mote.x += math.sin(self.elapsed * mote.speed + mote.phase) * dt * 0.18
            mote.y += math.cos(self.elapsed * mote.speed * 0.7 + mote.phase) * dt * 0.08

    def _draw_backdrop_source(self, canvas: FrameBuffer) -> None:
        if self.config["backdrop"]["source"] != "pelagic":
            return
        for y in range(3, self.height - 3):
            depth = min(7, y * 8 // max(1, self.height))
            stride = 5 + depth % 3
            offset = (y * 7) % stride
            glyph = "." if depth < 4 else "·"
            for x in range(offset, self.width, stride):
                canvas.put(x, y, glyph, self.backdrop_shades[depth])

    def _draw_backdrop_effects(self, canvas: FrameBuffer) -> None:
        backdrop = self.config["backdrop"]
        if not backdrop["effectsEnabled"] or backdrop["effectIntensity"] <= 0:
            return

        intensity = backdrop["effectIntensity"]
        palette = self.palette
        band_count = max(1, (intensity + 24) // 25)
        for band in range(band_count):
            centre = int(self.height * (band + 1) / (band_count + 1))
            for x in range((band + self.frame // 3) % 3, self.width, 3):
                y = centre + int(round(math.sin(x * 0.08 + self.elapsed * (0.45 + band * 0.09) + band) * 1.8))
                glyph = "~" if (x // 3 + band + self.frame // 10) % 4 else "─"
                canvas.put(x, y, glyph, palette["dim"] if band & 1 else palette["water"])

        scanline_spacing = max(5, 15 - intensity // 10)
        for y in range(4, self.height - 4, scanline_spacing):
            phase = (y + self.frame // 6) % 7
            for x in range(phase, self.width, 7):
                canvas.put(x, y, ".", self.backdrop_shades[min(7, y * 8 // max(1, self.height))])

        particle_count = self.width * self.height * intensity // 35000
        for particle in range(particle_count):
            x = (particle * 47 + self.frame // 8) % self.width
            y = 3 + (particle * 29 + self.frame // 16) % max(1, self.height - 7)
            canvas.put(x, y, "·", palette["dim"])

    def _draw_water(self, canvas: FrameBuffer) -> None:
        palette = self.palette
        for x in range(0, self.width, 2):
            surface = 2 + int(round(math.sin(x * 0.13 + self.elapsed * 0.7)))
            char = "~" if (x // 2 + self.frame // 8) % 3 else "_"
            canvas.put(x, surface, char, palette["caustic"])
        for mote in self.motes:
            brightness = (math.sin(self.elapsed * 1.6 + mote.phase) + 1) * 0.5
            char = "." if brightness < 0.72 else "+"
            colour = palette["dim"] if char == "." else palette["water"]
            canvas.put(int(mote.x), int(mote.y), char, colour)

        # Narrow shafts of terminal light descend from the animated surface.
        for shaft in range(3):
            centre = int((self.width * (shaft + 0.7) / 3.5 + self.elapsed * (shaft + 1) * 0.35) % self.width)
            for y in range(4, min(self.height - 5, 15 + shaft * 3)):
                x = centre + int(math.sin(y * 0.22 + self.elapsed) * 2)
                if (y + shaft) % 3 == 0:
                    canvas.put(x, y, ":", palette["dim"])

    def _draw_habitat(self, canvas: FrameBuffer) -> None:
        palette = self.palette
        floor = self.height - 3
        reef_density = self.config["art"].get("reefDensity", self.config["art"].get("vegetationVolume", 50))
        ratio = reef_density / 100.0

        for x in range(self.width):
            ridge = int(1.4 * math.sin(x * 0.09) + 0.7 * math.sin(x * 0.31))
            y = floor + ridge // 2
            canvas.put(x, y, "_" if x % 4 else ".", palette["sand"])
            if y + 1 < self.height:
                canvas.put(x, y + 1, ".", palette["rock"])

        if reef_density > 0:
            # 1. Kelp columns scale in density and height with reef density
            max_stalks = max(1, self.width // 7)
            stalk_count = max(1, int(round(max_stalks * ratio)))
            height_scale = 0.45 + 0.85 * ratio
            for plant in range(stalk_count):
                anchor = int((plant * (self.width * 0.6180339887) + 5) % (self.width - 8)) + 4
                base_height = 4 + (plant * 7 + (plant % 3) * 5) % 8
                stalk_h = max(2, min(self.height - 5, int(round(base_height * height_scale))))
                for segment in range(stalk_h):
                    y = floor - segment
                    sway = int(round(math.sin(self.elapsed * (0.65 + (plant % 5) * 0.08) + segment * 0.48 + plant * 1.3)))
                    if 0 <= anchor + sway < self.width:
                        canvas.put(anchor + sway, y, "}" if sway >= 0 else "{", palette["kelp"])
                if 0 <= anchor < self.width:
                    canvas.put(anchor, floor + 1, "Y", palette["kelp"])

            # 2. Central branching coral scales in tiers and height
            coral_tiers = min(5, max(2, int(round(2 + 3 * ratio))))
            full_coral_lines = (
                "   \\ | /   ",
                "  \\ \\|/ /  ",
                "---\\ | /---",
                "    \\|/    ",
                "     Y     ",
            )
            active_coral = full_coral_lines[-coral_tiers:]
            coral_x = self.width // 2 + int(math.sin(self.width) * self.width * 0.04)
            start_y = floor - len(active_coral) + 2
            for row, line in enumerate(active_coral):
                canvas.text(coral_x - 5, start_y + row, line, palette["coral"])

            # 3. Secondary left staghorn / fan coral formations
            if reef_density >= 35:
                left_cx = max(8, self.width // 4)
                left_lines = (" \\ | / ", "--\\|/--", "   Y   ") if reef_density >= 70 else (" \\|/ ", "  Y  ")
                ly = floor - len(left_lines) + 1
                for row, line in enumerate(left_lines):
                    canvas.text(left_cx - len(line) // 2, ly + row, line, palette["coral"])

            # 4. Secondary right table coral / sea plume formations
            if reef_density >= 55:
                right_cx = min(self.width - 10, self.width * 3 // 4)
                right_lines = (" / | \\ ", "--/|\\--", "   Y   ") if reef_density >= 80 else (" /|\\ ", "  Y  ")
                ry = floor - len(right_lines) + 1
                for row, line in enumerate(right_lines):
                    canvas.text(right_cx - len(line) // 2, ry + row, line, palette["coral"])

            # 5. Additional multi-point sea anemones and micro-flora
            if reef_density >= 75:
                for fx in (max(14, self.width // 8), min(self.width - 16, self.width * 7 // 8)):
                    canvas.text(fx, floor - 1, "\\|/", palette["coral"])

        for rock_x, glyph in ((2, "[__]"), (self.width // 3, "(_/\\_)"), (self.width - 9, "[___]")):
            canvas.text(rock_x, floor, glyph, palette["rock"])

    def _draw_bubbles(self, canvas: FrameBuffer) -> None:
        palette = self.palette
        glyphs = (".", "o", "O")
        for bubble in self.bubbles:
            canvas.put(int(bubble.x), int(bubble.y), glyphs[bubble.size], palette["caustic"])
            if bubble.size == 2 and bubble.y > 5:
                canvas.put(int(bubble.x) - 1, int(bubble.y), "·", palette["water"])

    def _draw_fish(self, canvas: FrameBuffer) -> None:
        for fish in sorted(self.fish, key=lambda item: item.base_y):
            frame_index = int(self.elapsed * (2.2 + fish.speed * 0.08) + fish.frame_phase) & 1
            lines = SPRITES[fish.species][frame_index]
            if fish.direction < 0:
                lines = mirror_sprite(lines)
            body, accent, shadow = FISH_COLOURS[fish.species]
            y = int(round(fish.base_y + math.sin(self.elapsed * fish.bob_rate + fish.phase) * fish.bob_height))
            x = int(round(fish.x))
            for row, line in enumerate(lines):
                for column, char in enumerate(line):
                    if char == " ":
                        continue
                    if char in "oO@#=|":
                        colour = accent
                    elif char in "_.'~-":
                        colour = shadow
                    else:
                        colour = body
                    canvas.put(x + column, y + row, char, colour)

    def _draw_status_display(self, canvas: FrameBuffer) -> None:
        if not self.config["art"]["showTelemetry"]:
            return
        palette = self.palette
        fish_count = len(self.fish)
        title = " OMARCHARIUM // PELAGIC TERMINAL ENVIRONMENT "
        right = f" BIOMASS {fish_count:02d} // {self.config['art']['palette'].upper()} "
        canvas.text(1, 0, title[: max(0, self.width - 2)], palette["text"])
        if len(right) + 1 < self.width:
            canvas.text(self.width - len(right) - 1, 0, right, palette["caustic"])
        footer = (
            "[ any key / click / pointer movement returns to surface ]"
            if self.config["integration"]["exitOnPointerMotion"]
            else "[ any key / click returns to surface ]"
        )
        if len(footer) + 2 < self.width:
            canvas.text((self.width - len(footer)) // 2, self.height - 1, footer, palette["dim"])

    def _draw_backdrop_notice(self, canvas: FrameBuffer) -> None:
        if not self.config["art"]["showTelemetry"] or not self.backdrop_notice:
            return
        notice = f"[ {self.backdrop_notice} ]"
        canvas.text(max(1, (self.width - len(notice)) // 2), self.height - 2, notice[: self.width - 2], self.palette["coral"])

    def render(self) -> FrameBuffer:
        canvas = FrameBuffer(self.width, self.height)
        self._draw_backdrop_source(canvas)
        self._draw_backdrop_effects(canvas)
        self._draw_water(canvas)
        self._draw_habitat(canvas)
        self._draw_bubbles(canvas)
        self._draw_fish(canvas)
        self._draw_status_display(canvas)
        self._draw_backdrop_notice(canvas)
        return canvas


class AmbientAudio:
    """Water and bubble synthesis streamed directly to PipeWire."""

    def __init__(
        self,
        volume: int,
        runtime_dir: Path,
        diagnostic: bool = False,
        water: bool = True,
        bubbles: bool = True,
    ) -> None:
        self.volume = max(0.0, min(1.0, volume / 100.0))
        self.runtime_dir = runtime_dir
        self.diagnostic = diagnostic
        self.water = bool(water)
        self.bubbles = bool(bubbles)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.lock_file: Any = None
        self.last_error = ""
        self.rng = random.Random(os.getpid() ^ int(time.time()))
    @staticmethod
    def playback_command() -> list[str]:
        return [
            "pw-cat", "--playback", "--raw", "--format", "s16",
            "--rate", "24000", "--channels", "2", "-",
        ]

    def start(self) -> bool:
        if self.volume <= 0:
            self.last_error = "volume is zero"
            return False
        if not self.diagnostic and not self.water and not self.bubbles:
            self.last_error = "water and bubble audio components are both disabled"
            return False
        if not shutil.which("pw-cat"):
            self.last_error = "pw-cat is unavailable; install PipeWire tools"
            return False
        try:
            ensure_private_directory(self.runtime_dir)
            self.lock_file = open_lock_file(self.runtime_dir / "audio.lock")
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if self.lock_file:
                self.lock_file.close()
            self.lock_file = None
            self.last_error = "another Omarcharium process already owns the audio stream"
            return False
        except OSError as error:
            if self.lock_file:
                self.lock_file.close()
            self.lock_file = None
            self.last_error = f"cannot create the audio lock: {error}"
            return False
        try:
            self.process = subprocess.Popen(
                self.playback_command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            self.last_error = f"cannot start pw-cat: {error}"
            self.close()
            return False
        self.thread = threading.Thread(target=self._synthesise, name="omarcharium-audio", daemon=True)
        self.thread.start()
        time.sleep(0.08)
        if self.process.poll() is not None:
            message = ""
            if self.process.stderr:
                try:
                    message = self.process.stderr.read().decode("utf-8", errors="replace").strip()
                except OSError:
                    pass
            self.last_error = message or f"pw-cat exited with status {self.process.returncode}"
            self.close()
            return False
        return True

    def _synthesise(self) -> None:
        assert self.process and self.process.stdin
        sample_rate = 24000
        block_size = 480
        low_noise = 0.0
        wave_phase = 0.0
        bubble_remaining = 0
        bubble_phase = 0.0
        bubble_length = 1
        bubble_start_frequency = 700.0
        rendered_samples = 0
        diagnostic_frequencies = (440.0, 660.0, 880.0)
        while not self.stop_event.is_set() and self.process.poll() is None:
            block = bytearray(block_size * 4)
            for index in range(block_size):
                water = 0.0
                if self.water:
                    low_noise = low_noise * 0.985 + self.rng.uniform(-1.0, 1.0) * 0.015
                    wave_phase += math.tau * 0.17 / sample_rate
                    water = low_noise * 1.35 + math.sin(wave_phase) * 0.12
                if self.bubbles and bubble_remaining <= 0 and self.rng.random() < 0.00008:
                    bubble_length = self.rng.randint(1200, 3200)
                    bubble_remaining = bubble_length
                    bubble_start_frequency = self.rng.uniform(420.0, 920.0)
                    bubble_phase = 0.0
                bubble = 0.0
                if self.bubbles and bubble_remaining > 0:
                    progress = 1.0 - bubble_remaining / bubble_length
                    frequency = bubble_start_frequency * (1.0 + progress * 1.7)
                    bubble_phase += math.tau * frequency / sample_rate
                    envelope = math.sin(math.pi * progress) ** 2
                    bubble = math.sin(bubble_phase) * envelope * 0.48
                    bubble_remaining -= 1
                diagnostic_tone = 0.0
                if self.diagnostic and rendered_samples < int(sample_rate * 1.8):
                    note = min(2, rendered_samples // int(sample_rate * 0.6))
                    note_sample = rendered_samples % int(sample_rate * 0.6)
                    note_progress = note_sample / (sample_rate * 0.6)
                    note_envelope = math.sin(math.pi * note_progress) ** 2
                    note_phase = math.tau * diagnostic_frequencies[note] * rendered_samples / sample_rate
                    diagnostic_tone = math.sin(note_phase) * note_envelope * 0.42

                sample = int(max(-1.0, min(1.0, (water + bubble + diagnostic_tone) * self.volume)) * 32767)
                struct.pack_into("<hh", block, index * 4, sample, sample)
                rendered_samples += 1
            try:
                self.process.stdin.write(block)
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                break

    def close(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=0.3)
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            self.lock_file.close()
            self.lock_file = None


class RasterBackdrop:
    """Prepare and place one validated local image through the Kitty protocol."""

    IMAGE_CODERS = {
        ".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png",
        ".gif": "gif", ".bmp": "bmp", ".webp": "webp",
    }
    MAX_FILE_BYTES = 32 * 1024 * 1024
    MAX_PIXELS = 24_000_000
    MAX_CACHE_FILES = 16
    MAX_CACHE_BYTES = 128 * 1024 * 1024
    IMAGE_ID = 7321

    def __init__(self, config: dict[str, Any]) -> None:
        self.settings = config["backdrop"]
        self.cached_path: Path | None = None
        self.error = ""

    @staticmethod
    def terminal_supported(environment: dict[str, str] | None = None) -> bool:
        values = os.environ if environment is None else environment
        identity = " ".join((
            values.get("TERM_PROGRAM", ""),
            values.get("TERM", ""),
        )).lower()
        return "ghostty" in identity or "kitty" in identity

    def _source_path(self) -> Path | None:
        raw_path = self.settings.get("imagePath", "")
        if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
            self.error = "custom image is not selected · using plain depth"
            return None
        try:
            path = Path(raw_path).expanduser().resolve(strict=True)
            metadata = path.stat()
        except OSError:
            self.error = "custom image is missing or unreadable · using plain depth"
            return None
        if not path.is_file() or path.suffix.lower() not in self.IMAGE_CODERS:
            self.error = "custom image type is unsupported · using plain depth"
            return None
        if metadata.st_size > self.MAX_FILE_BYTES:
            self.error = "custom image exceeds 32 MiB · using plain depth"
            return None
        return path

    @classmethod
    def image_spec(cls, source: Path) -> str:
        return f"{cls.IMAGE_CODERS[source.suffix.lower()]}:{source}[0]"

    @staticmethod
    def _magick_prefix(executable: str) -> list[str]:
        return [
            executable,
            "-limit", "memory", "128MiB",
            "-limit", "map", "256MiB",
            "-limit", "disk", "256MiB",
        ]

    @staticmethod
    def _owned_regular_file(path: Path) -> bool:
        try:
            metadata = path.lstat()
        except OSError:
            return False
        return stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()

    @staticmethod
    def _bounded_copy_and_hash(handle: Any, destination_file: Any, size: int) -> str:
        """Copy at most *size* bytes from *handle* into *destination_file*
        while hashing them, so the amount read is bounded by the length we
        already validated rather than by whatever the source grows to."""
        digest = hashlib.sha256()
        remaining = size
        while remaining > 0:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            destination_file.write(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        return digest.hexdigest()

    def _pin_source(self, source: Path, cache_root: Path) -> tuple[Path, str] | None:
        """Open *source* exactly once and copy its bytes into a private
        0600 file inside our own 0700 cache directory before any decoding
        happens. Both the identify and convert steps operate on this
        pinned snapshot, so a concurrent writer at *source* (the picker
        scans shared, writable directories such as Downloads) cannot swap
        the bytes between the size/pixel check and the eventual decode."""
        try:
            fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_CLOEXEC)
        except OSError:
            self.error = "custom image is missing or unreadable · using plain depth"
            return None
        snapshot_path: Path | None = None
        try:
            with os.fdopen(fd, "rb") as handle:
                file_stat = os.fstat(handle.fileno())
                if not stat.S_ISREG(file_stat.st_mode):
                    self.error = "custom image type is unsupported · using plain depth"
                    return None
                if file_stat.st_size > self.MAX_FILE_BYTES:
                    self.error = "custom image exceeds 32 MiB · using plain depth"
                    return None
                suffix = source.suffix.lower()
                with tempfile.NamedTemporaryFile(
                    dir=cache_root, prefix=".snapshot-", suffix=suffix, delete=False,
                ) as snapshot_file:
                    snapshot_path = Path(snapshot_file.name)
                    content_hash = self._bounded_copy_and_hash(handle, snapshot_file, file_stat.st_size)
            snapshot_path.chmod(0o600)
            return snapshot_path, content_hash
        except OSError:
            self.error = "custom image snapshot failed · using plain depth"
            if snapshot_path is not None:
                snapshot_path.unlink(missing_ok=True)
            return None

    @classmethod
    def identify_dimensions(
        cls, source: Path, executable: str, environment: dict[str, str],
    ) -> tuple[int, int] | None:
        try:
            identified = subprocess.run(
                [
                    executable, "identify", *cls._magick_prefix(executable)[1:],
                    "-ping", "-format", "%w %h", cls.image_spec(source),
                ],
                check=False, capture_output=True, text=True, timeout=10, env=environment,
            )
            width_text, height_text = identified.stdout.strip().split()
            width, height = int(width_text), int(height_text)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
        if identified.returncode != 0 or width < 1 or height < 1 or width * height > cls.MAX_PIXELS:
            return None
        return width, height

    @classmethod
    def prune_cache(cls, cache_root: Path, current: Path) -> None:
        candidates = [
            path for path in cache_root.glob("backdrop-*.png")
            if path != current and cls._owned_regular_file(path)
        ]
        candidates.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
        kept_files = 1
        kept_bytes = current.stat().st_size
        for path in candidates:
            size = path.stat().st_size
            keep = (
                kept_files < cls.MAX_CACHE_FILES
                and kept_bytes + size <= cls.MAX_CACHE_BYTES
            )
            if keep:
                kept_files += 1
                kept_bytes += size
            else:
                path.unlink(missing_ok=True)

    def prepare(self) -> bool:
        source = self._source_path()
        if source is None:
            return False
        executable = shutil.which("magick")
        if executable is None:
            self.error = "ImageMagick is unavailable · using plain depth"
            return False

        cache_root = user_cache_home() / "omarcharium"
        try:
            ensure_private_directory(cache_root)
        except OSError:
            self.error = "custom image cache is unsafe · using plain depth"
            return False

        pinned = self._pin_source(source, cache_root)
        if pinned is None:
            return False
        snapshot, content_hash = pinned
        try:
            environment = os.environ.copy()
            environment["MAGICK_TEMPORARY_PATH"] = str(cache_root)
            dimensions = self.identify_dimensions(snapshot, executable, environment)
            if dimensions is None:
                self.error = "custom image could not be decoded or exceeds 24 megapixels · using plain depth"
                return False

            signature = "\0".join((
                content_hash, self.settings["fitMode"], str(self.settings["dimming"]),
            ))
            cache_key = hashlib.sha256(signature.encode("utf-8")).hexdigest()
            output = cache_root / f"backdrop-{cache_key}.png"
            lock_path = cache_root / "backdrop-cache.lock"
            temporary: Path | None = None

            try:
                with open_lock_file(lock_path) as lock_file:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    output_exists = output.exists() or output.is_symlink()
                    if output_exists and not self._owned_regular_file(output):
                        self.error = "custom image cache entry is unsafe · using plain depth"
                        return False
                    if not output_exists:
                        with tempfile.NamedTemporaryFile(
                            dir=cache_root, prefix=f".{cache_key}.", suffix=".tmp", delete=False,
                        ) as temporary_file:
                            temporary = Path(temporary_file.name)
                        fit_mode = self.settings["fitMode"]
                        if fit_mode == "cover":
                            fit_args = ["-resize", "1920x1080^", "-gravity", "center", "-extent", "1920x1080"]
                        elif fit_mode == "contain":
                            fit_args = ["-resize", "1920x1080", "-gravity", "center", "-extent", "1920x1080"]
                        else:
                            fit_args = ["-resize", "1920x1080>", "-gravity", "center", "-extent", "1920x1080"]
                        brightness = (100 - self.settings["dimming"]) / 100
                        converted = subprocess.run(
                            [
                                *self._magick_prefix(executable), self.image_spec(snapshot), "-auto-orient",
                                "-background", "black", *fit_args,
                                "-alpha", "remove", "-evaluate", "multiply", f"{brightness:.2f}",
                                "-strip", f"png:{temporary}",
                            ],
                            check=False, capture_output=True, timeout=30, env=environment,
                        )
                        if converted.returncode != 0 or not self._owned_regular_file(temporary):
                            self.error = "custom image conversion failed · using plain depth"
                            return False
                        temporary.chmod(0o600)
                        os.replace(temporary, output)
                        temporary = None
                    output.chmod(0o600)
                    self.prune_cache(cache_root, output)
            except (OSError, subprocess.TimeoutExpired):
                self.error = "custom image cache failed · using plain depth"
                return False
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        finally:
            snapshot.unlink(missing_ok=True)

        self.cached_path = output
        self.error = ""
        return True

    @classmethod
    def delete_sequence(cls) -> str:
        return f"\x1b_Ga=d,d=I,i={cls.IMAGE_ID},q=2;\x1b\\"

    @classmethod
    def placement_sequence(cls, path: Path, width: int, height: int) -> str:
        payload = base64.standard_b64encode(os.fsencode(path)).decode("ascii")
        return (
            f"\x1b_Ga=T,f=100,t=f,i={cls.IMAGE_ID},c={max(1, width)},r={max(1, height)},"
            f"z=-1,q=2,C=1;{payload}\x1b\\"
        )

    def display(self, width: int, height: int) -> None:
        if self.cached_path is None:
            return
        sys.stdout.write(self.delete_sequence())
        sys.stdout.write(self.placement_sequence(self.cached_path, width, height))
        sys.stdout.flush()

    def close(self) -> None:
        if self.cached_path is not None:
            sys.stdout.write(self.delete_sequence())
            sys.stdout.flush()

class DismissalInput:
    """Classify SGR mouse reports without swallowing keyboard input."""

    _MOUSE_PREFIX = b"\x1b[<"

    def __init__(self, exit_on_pointer_motion: bool, pending_timeout: float = 0.06) -> None:
        self.exit_on_pointer_motion = exit_on_pointer_motion
        self.pending_timeout = pending_timeout
        self.buffer = bytearray()
        self.pending_since: float | None = None

    def feed(self, data: bytes, now: float | None = None) -> bool:
        timestamp = time.monotonic() if now is None else now
        if data:
            if not self.buffer:
                self.pending_since = timestamp
            self.buffer.extend(data)

        while self.buffer:
            probe = bytes(self.buffer)
            if len(probe) < len(self._MOUSE_PREFIX):
                return not self._MOUSE_PREFIX.startswith(probe)
            if not probe.startswith(self._MOUSE_PREFIX):
                return True

            terminator = -1
            for index, byte in enumerate(self.buffer[3:], start=3):
                if byte in (ord("M"), ord("m")):
                    terminator = index
                    break
                if byte not in b"0123456789;":
                    return True

            if terminator < 0:
                return len(self.buffer) > 32

            fields = bytes(self.buffer[3:terminator]).split(b";")
            if len(fields) != 3 or not all(field.isdigit() for field in fields):
                return True
            button_code = int(fields[0])
            del self.buffer[:terminator + 1]
            if button_code & 32:
                if self.exit_on_pointer_motion:
                    return True
            else:
                return True

        self.pending_since = None
        return False

    def expired(self, now: float | None = None) -> bool:
        if not self.buffer or self.pending_since is None:
            return False
        timestamp = time.monotonic() if now is None else now
        return timestamp - self.pending_since >= self.pending_timeout


class TerminalSession:
    def __init__(self, background: RGB) -> None:
        self.background = background
        self.original_attributes: list[Any] | None = None
        self.active = False

    def __enter__(self) -> "TerminalSession":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError("Omarcharium interactive mode requires a terminal")
        self.original_attributes = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
        r, g, b = self.background
        sys.stdout.write(
            "\x1b[?1049h\x1b[2J\x1b[H\x1b[?25l"
            "\x1b[?1003h\x1b[?1006h"
            f"\x1b]11;rgb:{r:02x}/{g:02x}/{b:02x}\x07"
        )
        sys.stdout.flush()
        self.active = True
        return self

    def __exit__(self, *_: Any) -> None:
        if not self.active:
            return
        sys.stdout.write("\x1b[?1003l\x1b[?1006l\x1b[0m\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        if self.original_attributes:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.original_attributes)
        self.active = False


def terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size(fallback=(120, 36))
    return clamp_dimensions(size.columns, size.lines)


def dismiss_screensaver_windows() -> None:
    try:
        subprocess.Popen(
            ["pkill", "-f", "[o]rg.omarchy.screensaver"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def run_interactive(config: dict[str, Any], seed: int, sound_override: bool | None) -> int:
    width, height = terminal_size()
    scene = OceanScene(width, height, config, seed)
    palette = scene.palette
    runtime_dir = runtime_directory()
    sound_enabled = config["sound"]["enabled"] if sound_override is None else sound_override
    audio = AmbientAudio(
        config["sound"]["volume"],
        runtime_dir,
        water=config["sound"]["water"],
        bubbles=config["sound"]["bubbles"],
    )
    dismissal_input = DismissalInput(config["integration"]["exitOnPointerMotion"])
    raster = RasterBackdrop(config)
    raster_active = False
    if config["backdrop"]["source"] == "image":
        if not raster.terminal_supported():
            scene.backdrop_notice = "custom images require Ghostty or Kitty · using plain depth"
        elif raster.prepare():
            raster_active = True
        else:
            scene.backdrop_notice = raster.error
    stop_requested = False
    user_dismissed = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
        previous_handlers[sig] = signal.signal(sig, stop_handler)

    try:
        with TerminalSession(palette["background"]):
            try:
                if raster_active:
                    raster.display(width, height)
                if sound_enabled:
                    audio.start()
                started = time.monotonic()
                previous = started
                next_frame = started
                while not stop_requested:
                    now = time.monotonic()
                    if dismissal_input.expired(now):
                        user_dismissed = True
                        break
                    if now - started > 0.35 and select.select([sys.stdin], [], [], 0)[0]:
                        if dismissal_input.feed(os.read(sys.stdin.fileno(), 4096), now):
                            user_dismissed = True
                            break
                    new_width, new_height = terminal_size()
                    if (new_width, new_height) != (width, height):
                        width, height = new_width, new_height
                        scene.resize(width, height)
                        if raster_active:
                            raster.display(width, height)
                    scene.update(now - previous)
                    previous = now
                    sys.stdout.write(scene.render().ansi())
                    sys.stdout.flush()
                    next_frame += 1.0 / 24.0
                    delay = next_frame - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    else:
                        next_frame = time.monotonic()
            finally:
                if raster_active:
                    raster.close()
    finally:
        audio.close()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    if user_dismissed:
        dismiss_screensaver_windows()
    return 0

def run_audio_test(config: dict[str, Any], seconds: float) -> int:
    """Exercise PipeWire without requiring an interactive terminal."""
    runtime_dir = runtime_directory()
    duration = max(1.0, min(60.0, seconds))
    volume = max(55, int(config["sound"]["volume"]))
    water_enabled = bool(config["sound"]["water"])
    bubbles_enabled = bool(config["sound"]["bubbles"])
    audio = AmbientAudio(
        volume,
        runtime_dir,
        diagnostic=True,
        water=water_enabled,
        bubbles=bubbles_enabled,
    )
    if not audio.start():
        print(f"omarcharium audio test failed: {audio.last_error}", file=sys.stderr)
        return 3
    if water_enabled and bubbles_enabled:
        texture_desc = "water and bubbles"
    elif water_enabled:
        texture_desc = "water flow"
    elif bubbles_enabled:
        texture_desc = "bubbles"
    else:
        texture_desc = "silence (both sound channels disabled)"
    print(
        f"Omarcharium audio test active at {volume}% for {duration:g}s. "
        f"Listen for three rising tones, then {texture_desc}.",
        flush=True,
    )
    deadline = time.monotonic() + duration
    try:
        while time.monotonic() < deadline:
            if audio.process and audio.process.poll() is not None:
                print("omarcharium audio test failed: PipeWire stream stopped", file=sys.stderr)
                return 3
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        audio.close()
    print("Omarcharium audio test complete.", flush=True)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TTE-inspired tropical terminal aquarium")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="configuration JSON path")
    parser.add_argument("--seed", type=int, default=None, help="deterministic scene seed")
    parser.add_argument("--snapshot", action="store_true", help="render one plain-text frame and exit")
    parser.add_argument("--width", type=int, default=100, help="snapshot width")
    parser.add_argument("--height", type=int, default=32, help="snapshot height")
    parser.add_argument("--check-config", action="store_true", help="print the normalised configuration and exit")
    parser.add_argument("--check-backdrop", action="store_true", help="validate and prepare the configured custom image")
    parser.add_argument(
        "--json", action="store_true",
        help="with --check-backdrop, emit a single-line JSON object instead of human-readable text",
    )
    parser.add_argument(
        "--audio-test", type=float, nargs="?", const=8.0, default=None, metavar="SECONDS",
        help="play an audible PipeWire diagnostic without requiring a terminal",
    )
    sound = parser.add_mutually_exclusive_group()
    sound.add_argument("--sound", action="store_true", help="enable ambience for this run")
    sound.add_argument("--no-sound", action="store_true", help="disable ambience for this run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = load_config(args.config)
    if args.check_config:
        print(json.dumps(config, indent=2, sort_keys=True))
        return 0
    if args.check_backdrop:
        raster = RasterBackdrop(config)
        ok = raster.prepare()
        if args.json:
            print(json.dumps({
                "ok": ok,
                "path": str(raster.cached_path) if ok else None,
                "error": "" if ok else raster.error,
                "terminalSupported": raster.terminal_supported(),
            }))
            return 0 if ok else 4
        if not ok:
            print(f"omarcharium backdrop check failed: {raster.error}", file=sys.stderr)
            return 4
        compatibility = "supported" if raster.terminal_supported() else "plain fallback in this terminal"
        print(f"Omarcharium custom backdrop ready: {raster.cached_path} ({compatibility})")
        return 0
    if args.audio_test is not None:
        return run_audio_test(config, args.audio_test)
    seed = args.seed if args.seed is not None else (os.getpid() ^ time.time_ns()) & 0xFFFFFFFF
    if args.snapshot:
        scene = OceanScene(args.width, args.height, config, seed)
        scene.update(1.0 / 24.0)
        print(scene.render().plain())
        return 0
    sound_override = True if args.sound else False if args.no_sound else None
    try:
        return run_interactive(config, seed, sound_override)
    except RuntimeError as error:
        print(f"omarcharium: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
