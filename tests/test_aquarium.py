from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("omarcharium_aquarium", ROOT / "scripts" / "aquarium.py")
assert SPEC and SPEC.loader
AQUARIUM = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AQUARIUM
SPEC.loader.exec_module(AQUARIUM)

HAVE_MAGICK = shutil.which("magick") is not None
requires_magick = unittest.skipUnless(HAVE_MAGICK, "ImageMagick (magick) is not installed")


class ConfigurationTests(unittest.TestCase):
    def test_normalisation_clamps_public_configuration_contract(self) -> None:
        config = AQUARIUM.normalise_config({
            "species": {"neon_tetra": 999, "puffer": -4, "unknown": 12},
            "art": {"palette": "not-a-palette", "bubbleDensity": 155, "current": 0, "showTelemetry": 0, "reefDensity": 400},
            "backdrop": {"source": "unknown", "effectsEnabled": "yes", "effectIntensity": 400},
            "sound": {"enabled": 1, "volume": "41"},
            "integration": {"idleEnabled": False, "exitOnPointerMotion": False},
        })

        self.assertEqual(config["species"]["neon_tetra"], 20)
        self.assertEqual(config["species"]["puffer"], 0)
        self.assertNotIn("unknown", config["species"])
        self.assertEqual(config["art"]["palette"], "lagoon")
        self.assertEqual(config["art"]["bubbleDensity"], 100)
        self.assertEqual(config["art"]["current"], 0.35)
        self.assertFalse(config["art"]["showTelemetry"])
        self.assertEqual(config["art"]["reefDensity"], 100)
        self.assertEqual(config["backdrop"]["source"], "plain")
        self.assertFalse(config["backdrop"]["effectsEnabled"])
        self.assertEqual(config["backdrop"]["effectIntensity"], 100)
        self.assertTrue(config["sound"]["enabled"])
        self.assertEqual(config["sound"]["volume"], 41)
        self.assertTrue(config["sound"]["water"])
        self.assertTrue(config["sound"]["bubbles"])
        self.assertFalse(config["integration"]["idleEnabled"])
        self.assertFalse(config["integration"]["exitOnPointerMotion"])

    def test_status_display_defaults_off_without_overwriting_saved_choice(self) -> None:
        self.assertFalse(AQUARIUM.normalise_config({})["art"]["showTelemetry"])
        self.assertFalse(AQUARIUM.normalise_config({"art": {"showTelemetry": False}})["art"]["showTelemetry"])
        self.assertTrue(AQUARIUM.normalise_config({"art": {"showTelemetry": True}})["art"]["showTelemetry"])

    def test_legacy_vegetation_volume_key_is_accepted_as_reef_density(self) -> None:
        config = AQUARIUM.normalise_config({"art": {"vegetationVolume": 75}})
        self.assertEqual(config["art"]["reefDensity"], 75)

    def test_sound_channels_are_normalized_and_accept_aliases(self) -> None:
        config = AQUARIUM.normalise_config({
            "sound": {"water": False, "bubbles": True},
        })
        self.assertFalse(config["sound"]["water"])
        self.assertTrue(config["sound"]["bubbles"])

        config_alias = AQUARIUM.normalise_config({
            "sound": {"waterFlow": False, "bubblesEnabled": False},
        })
        self.assertFalse(config_alias["sound"]["water"])
        self.assertFalse(config_alias["sound"]["bubbles"])

        config_enabled_alias = AQUARIUM.normalise_config({
            "sound": {"waterEnabled": False},
        })
        self.assertFalse(config_enabled_alias["sound"]["water"])
        self.assertTrue(config_enabled_alias["sound"]["bubbles"])

    def test_malformed_pointer_motion_setting_uses_safe_default(self) -> None:
        config = AQUARIUM.normalise_config({"integration": {"exitOnPointerMotion": "false"}})
        self.assertTrue(config["integration"]["exitOnPointerMotion"])

    def test_invalid_file_uses_complete_packaged_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text("{ definitely not json", encoding="utf-8")
            config = AQUARIUM.load_config(path)

        defaults = json.loads((ROOT / "defaults.json").read_text(encoding="utf-8"))
        self.assertEqual(config, defaults)

    def test_image_backdrop_settings_are_normalized(self) -> None:
        config = AQUARIUM.normalise_config({
            "backdrop": {
                "source": "image",
                "imagePath": "/tmp/reef image.png",
                "fitMode": "invalid",
                "dimming": -20,
            },
        })
        self.assertEqual(config["backdrop"]["source"], "image")
        self.assertEqual(config["backdrop"]["imagePath"], "/tmp/reef image.png")
        self.assertEqual(config["backdrop"]["fitMode"], "cover")
        self.assertEqual(config["backdrop"]["dimming"], 0)

    def test_malformed_sections_use_packaged_defaults(self) -> None:
        config = AQUARIUM.normalise_config({
            "species": "many",
            "art": [],
            "backdrop": 42,
            "sound": None,
            "integration": "enabled",
        })
        defaults = json.loads((ROOT / "defaults.json").read_text(encoding="utf-8"))
        self.assertEqual(config, defaults)

    def test_oversized_configuration_is_rejected_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.json"
            path.write_bytes(b" " * (AQUARIUM.MAX_CONFIG_BYTES + 1))
            config = AQUARIUM.load_config(path)

        defaults = json.loads((ROOT / "defaults.json").read_text(encoding="utf-8"))
        self.assertEqual(config, defaults)



class RendererTests(unittest.TestCase):
    def test_mirroring_is_an_involution_for_every_fish_frame(self) -> None:
        for species, frames in AQUARIUM.SPRITES.items():
            for frame in frames:
                with self.subTest(species=species, frame=frame):
                    self.assertEqual(AQUARIUM.mirror_sprite(AQUARIUM.mirror_sprite(frame)), frame)

    def test_scene_population_and_snapshot_dimensions_match_configuration(self) -> None:
        config = AQUARIUM.normalise_config({
            "species": {key: 0 for key in AQUARIUM.SPRITES},
            "art": {"showTelemetry": False},
        })
        config["species"]["angelfish"] = 2
        config["species"]["puffer"] = 3
        scene = AQUARIUM.OceanScene(80, 24, config, seed=17)
        scene.update(1 / 24)
        snapshot = scene.render().plain().split("\n")

        self.assertEqual(len(scene.fish), 5)
        self.assertEqual(len(snapshot), 24)
        self.assertTrue(all(len(line) <= 80 for line in snapshot))
        self.assertIn("Y", "\n".join(snapshot))

    def test_scene_dimensions_are_bounded(self) -> None:
        self.assertEqual(
            AQUARIUM.clamp_dimensions(10**9, 10**9),
            (AQUARIUM.MAX_TERMINAL_COLUMNS, AQUARIUM.MAX_TERMINAL_LINES),
        )
        self.assertEqual(AQUARIUM.clamp_dimensions(-1, -1), (40, 16))

    def test_pelagic_backdrop_and_effect_overlay_are_independent_and_deterministic(self) -> None:
        base = {
            "species": {key: 0 for key in AQUARIUM.SPRITES},
            "art": {"showTelemetry": False},
            "backdrop": {"source": "pelagic", "effectsEnabled": False},
        }
        without_effects = AQUARIUM.OceanScene(80, 24, AQUARIUM.normalise_config(base), seed=23)
        first = without_effects.render().plain()
        repeated = AQUARIUM.OceanScene(80, 24, AQUARIUM.normalise_config(base), seed=23).render().plain()

        base["backdrop"]["effectsEnabled"] = True
        with_effects = AQUARIUM.OceanScene(80, 24, AQUARIUM.normalise_config(base), seed=23)
        effected = with_effects.render().plain()

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, effected)
        self.assertIn("·", first)
        self.assertIn("~", effected)

    def test_pelagic_backdrop_renders_in_every_palette(self) -> None:
        for palette in AQUARIUM.PALETTES:
            config = AQUARIUM.normalise_config({
                "art": {"palette": palette, "showTelemetry": False},
                "backdrop": {"source": "pelagic", "effectsEnabled": True},
            })
            scene = AQUARIUM.OceanScene(80, 24, config, seed=5)
            with self.subTest(palette=palette):
                self.assertIn("·", scene.render().plain())


    def test_reef_density_scales_coral_and_kelp(self) -> None:
        base = {
            "species": {key: 0 for key in AQUARIUM.SPRITES},
            "art": {"showTelemetry": False, "reefDensity": 0},
            "backdrop": {"source": "plain", "effectsEnabled": False},
        }
        bare = AQUARIUM.OceanScene(100, 28, AQUARIUM.normalise_config(base), seed=7).render().plain()
        self.assertNotIn("}", bare)
        self.assertNotIn("{", bare)
        self.assertNotIn("\\ | /", bare)

        base["art"]["reefDensity"] = 25
        low = AQUARIUM.OceanScene(100, 28, AQUARIUM.normalise_config(base), seed=7).render().plain()
        low_stalk_chars = low.count("}") + low.count("{")
        low_coral_chars = low.count("\\") + low.count("/") + low.count("|")

        base["art"]["reefDensity"] = 100
        dense = AQUARIUM.OceanScene(100, 28, AQUARIUM.normalise_config(base), seed=7).render().plain()
        dense_stalk_chars = dense.count("}") + dense.count("{")
        dense_coral_chars = dense.count("\\") + dense.count("/") + dense.count("|")

        self.assertGreater(low_stalk_chars, 0)
        self.assertGreater(dense_stalk_chars, low_stalk_chars * 2)
        self.assertGreater(dense_coral_chars, low_coral_chars * 2)

    def test_status_display_controls_all_text_including_backdrop_notice(self) -> None:
        config = AQUARIUM.normalise_config({
            "species": {key: 0 for key in AQUARIUM.SPRITES},
            "art": {"bubbleDensity": 0, "reefDensity": 0},
        })
        scene = AQUARIUM.OceanScene(100, 28, config, seed=7)
        without_notice = scene.render().plain()
        scene.backdrop_notice = "custom image unavailable"
        self.assertEqual(scene.render().plain(), without_notice)
        self.assertNotIn("OMARCHARIUM", without_notice)
        self.assertNotIn("BIOMASS", without_notice)
        self.assertNotIn("returns to surface", without_notice)

        config["art"]["showTelemetry"] = True
        with_status = scene.render().plain()
        self.assertIn("OMARCHARIUM", with_status)
        self.assertIn("BIOMASS", with_status)
        self.assertIn("returns to surface", with_status)
        self.assertIn("custom image unavailable", with_status)


class RasterBackdropTests(unittest.TestCase):
    def test_source_validation_accepts_only_bounded_local_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "reef image.png"
            image.write_bytes(b"not decoded during path validation")
            config = AQUARIUM.normalise_config({
                "backdrop": {"source": "image", "imagePath": str(image)},
            })
            raster = AQUARIUM.RasterBackdrop(config)
            self.assertEqual(raster._source_path(), image.resolve())

            text = root / "reef.txt"
            text.write_text("not an image", encoding="utf-8")
            config["backdrop"]["imagePath"] = str(text)
            rejected = AQUARIUM.RasterBackdrop(config)
            self.assertIsNone(rejected._source_path())
            self.assertIn("unsupported", rejected.error)

    def test_missing_image_uses_a_clear_fallback(self) -> None:
        config = AQUARIUM.normalise_config({
            "backdrop": {"source": "image", "imagePath": "/definitely/missing/reef.png"},
        })
        raster = AQUARIUM.RasterBackdrop(config)
        self.assertFalse(raster.prepare())
        self.assertIn("using plain depth", raster.error)

    def test_terminal_compatibility_and_protocol_placement_are_explicit(self) -> None:
        self.assertTrue(AQUARIUM.RasterBackdrop.terminal_supported({"TERM_PROGRAM": "ghostty"}))
        self.assertTrue(AQUARIUM.RasterBackdrop.terminal_supported({"TERM": "xterm-kitty"}))
        self.assertFalse(AQUARIUM.RasterBackdrop.terminal_supported({"TERM": "xterm-256color"}))

        sequence = AQUARIUM.RasterBackdrop.placement_sequence(Path("/tmp/reef.png"), 120, 36)
        self.assertIn("a=T", sequence)
        self.assertIn("t=f", sequence)
        self.assertIn("z=-1", sequence)
        self.assertIn("c=120,r=36", sequence)

    def test_image_decoder_is_forced_from_the_allowed_suffix(self) -> None:
        self.assertEqual(
            AQUARIUM.RasterBackdrop.image_spec(Path("/tmp/reef image.png")),
            "png:/tmp/reef image.png[0]",
        )

    def test_cache_pruning_keeps_current_and_enforces_file_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            current = cache / "backdrop-current.png"
            current.write_bytes(b"current")
            for index in range(AQUARIUM.RasterBackdrop.MAX_CACHE_FILES + 5):
                (cache / f"backdrop-{index:02d}.png").write_bytes(b"x")

            AQUARIUM.RasterBackdrop.prune_cache(cache, current)
            remaining = list(cache.glob("backdrop-*.png"))

        self.assertIn(current.name, {path.name for path in remaining})
        self.assertLessEqual(len(remaining), AQUARIUM.RasterBackdrop.MAX_CACHE_FILES)

    def test_pin_source_stores_a_bounded_private_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_root = root / "cache"
            cache_root.mkdir()
            image = root / "reef.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"pretend-pixels" * 4)
            config = AQUARIUM.normalise_config({
                "backdrop": {"source": "image", "imagePath": str(image)},
            })
            raster = AQUARIUM.RasterBackdrop(config)
            pinned = raster._pin_source(image, cache_root)
            self.assertIsNotNone(pinned)
            snapshot, digest = pinned
            self.assertTrue(snapshot.is_file())
            self.assertEqual(snapshot.parent, cache_root)
            self.assertEqual(snapshot.read_bytes(), image.read_bytes())
            self.assertEqual(digest, hashlib.sha256(image.read_bytes()).hexdigest())
            self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
            snapshot.unlink()

    def test_pin_source_rejects_bytes_beyond_the_authoritative_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_root = root / "cache"
            cache_root.mkdir()
            image = root / "reef.png"
            image.write_bytes(b"x" * 64)
            config = AQUARIUM.normalise_config({
                "backdrop": {"source": "image", "imagePath": str(image)},
            })
            raster = AQUARIUM.RasterBackdrop(config)
            with mock.patch.object(AQUARIUM.RasterBackdrop, "MAX_FILE_BYTES", 16):
                pinned = raster._pin_source(image, cache_root)
            self.assertIsNone(pinned)
            self.assertIn("using plain depth", raster.error)
            self.assertEqual(list(cache_root.glob(".snapshot-*")), [])

    @requires_magick
    def test_prepare_pins_bytes_so_a_later_source_swap_cannot_alter_the_converted_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "reef.png"
            subprocess.run(["magick", "-size", "4x4", "xc:red", str(original)], check=True)
            swapped = root / "swapped.png"
            subprocess.run(["magick", "-size", "4x4", "xc:blue", str(swapped)], check=True)

            config = AQUARIUM.normalise_config({
                "backdrop": {"source": "image", "imagePath": str(original), "fitMode": "cover", "dimming": 0},
            })
            raster = AQUARIUM.RasterBackdrop(config)
            real_identify = AQUARIUM.RasterBackdrop.identify_dimensions.__func__

            def racing_identify(cls, source, executable, environment):
                # Simulate a concurrent writer replacing the bytes at the
                # originally selected path only after they were pinned.
                original.write_bytes(swapped.read_bytes())
                return real_identify(cls, source, executable, environment)

            with tempfile.TemporaryDirectory() as cache_dir:
                with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache_dir}), \
                     mock.patch.object(AQUARIUM.RasterBackdrop, "identify_dimensions", classmethod(racing_identify)):
                    self.assertTrue(raster.prepare())
                pixel = subprocess.run(
                    [
                        "magick", str(raster.cached_path),
                        "-format", "%[fx:int(255*r)],%[fx:int(255*g)],%[fx:int(255*b)]", "info:",
                    ],
                    check=True, capture_output=True, text=True,
                ).stdout.strip()

        self.assertEqual(pixel, "255,0,0")


class BackdropCliTests(unittest.TestCase):
    def run_check_backdrop(
        self, config_path: Path, cache_home: Path, *, json_mode: bool,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["XDG_CACHE_HOME"] = str(cache_home)
        command = [
            sys.executable, str(ROOT / "scripts" / "aquarium.py"),
            "--config", str(config_path), "--check-backdrop",
        ]
        if json_mode:
            command.append("--json")
        return subprocess.run(command, capture_output=True, text=True, env=environment)

    def write_config(self, directory: Path, image: Path) -> Path:
        config_path = directory / "config.json"
        config_path.write_text(json.dumps({
            "backdrop": {"source": "image", "imagePath": str(image), "fitMode": "cover", "dimming": 20},
        }))
        return config_path

    @requires_magick
    def test_json_mode_returns_a_bounded_rendered_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "reef.png"
            subprocess.run(["magick", "-size", "8x8", "xc:red", str(image)], check=True)
            config_path = self.write_config(root, image)
            cache_home = root / "cache"

            result = self.run_check_backdrop(config_path, cache_home, json_mode=True)
            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            cached_path = Path(payload["path"])
            self.assertEqual(cached_path.parent, cache_home / "omarcharium")
            self.assertEqual(cached_path.stat().st_mode & 0o777, 0o600)
            details = subprocess.run(
                ["magick", str(cached_path), "-format", "%w %h %[fx:int(255*r)],%[fx:int(255*g)],%[fx:int(255*b)]", "info:"],
                check=True, capture_output=True, text=True,
            ).stdout.split()
            self.assertEqual(details[:2], ["1920", "1080"])
            red, green, blue = map(int, details[2].split(","))
            self.assertGreater(red, 0)
            self.assertEqual((green, blue), (0, 0))

    def test_json_mode_reports_missing_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self.write_config(root, root / "missing.png")
            result = self.run_check_backdrop(config_path, root / "cache", json_mode=True)

        self.assertEqual(result.returncode, 4)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["path"])
        self.assertIn("using plain depth", payload["error"])


class FilesystemSecurityTests(unittest.TestCase):
    def test_lock_open_refuses_symlinks_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("preserve me", encoding="utf-8")
            lock = root / "audio.lock"
            lock.symlink_to(target)

            with self.assertRaises(OSError):
                AQUARIUM.open_lock_file(lock)

            self.assertEqual(target.read_text(encoding="utf-8"), "preserve me")

    def test_runtime_fallback_stays_in_the_private_user_cache(self) -> None:
        original_runtime = os.environ.pop("XDG_RUNTIME_DIR", None)
        try:
            runtime = AQUARIUM.runtime_directory()
        finally:
            if original_runtime is not None:
                os.environ["XDG_RUNTIME_DIR"] = original_runtime

        self.assertEqual(runtime, AQUARIUM.user_cache_home() / "omarcharium" / "runtime")



class DismissalInputTests(unittest.TestCase):
    def test_pointer_motion_follows_setting(self) -> None:
        report = b"\x1b[<35;42;9M"
        self.assertTrue(AQUARIUM.DismissalInput(True).feed(report, now=1.0))
        self.assertFalse(AQUARIUM.DismissalInput(False).feed(report, now=1.0))

    def test_click_and_keyboard_always_dismiss(self) -> None:
        decoder = AQUARIUM.DismissalInput(False)
        self.assertTrue(decoder.feed(b"\x1b[<0;42;9M", now=1.0))
        self.assertTrue(AQUARIUM.DismissalInput(False).feed(b"x", now=1.0))

    def test_fragmented_motion_report_is_not_misclassified(self) -> None:
        decoder = AQUARIUM.DismissalInput(False)
        self.assertFalse(decoder.feed(b"\x1b[<35;42", now=1.0))
        self.assertFalse(decoder.feed(b";9M", now=1.01))

    def test_standalone_escape_expires_as_keyboard_input(self) -> None:
        decoder = AQUARIUM.DismissalInput(False)
        self.assertFalse(decoder.feed(b"\x1b", now=1.0))
        self.assertTrue(decoder.expired(now=1.07))


class AudioTests(unittest.TestCase):
    def test_pipewire_stream_is_explicitly_raw_pcm(self) -> None:
        command = AQUARIUM.AmbientAudio.playback_command()
        self.assertIn("--raw", command)
        self.assertEqual(command[-1], "-")
        self.assertEqual(command[command.index("--format") + 1], "s16")

    def test_audio_test_defaults_to_eight_seconds_without_a_tty(self) -> None:
        arguments = AQUARIUM.parse_args(["--audio-test"])
        self.assertEqual(arguments.audio_test, 8.0)
        self.assertTrue(AQUARIUM.parse_args(["--check-backdrop"]).check_backdrop)
    def test_ambient_audio_accepts_individual_channel_toggles(self) -> None:
        audio = AQUARIUM.AmbientAudio(50, Path("/tmp"), water=False, bubbles=True)
        self.assertFalse(audio.water)
        self.assertTrue(audio.bubbles)

    def test_ambient_audio_refuses_start_when_all_channels_disabled(self) -> None:
        audio = AQUARIUM.AmbientAudio(50, Path("/tmp"), water=False, bubbles=False)
        self.assertFalse(audio.start())
        self.assertEqual(audio.last_error, "water and bubble audio components are both disabled")

    def test_ambient_audio_refuses_start_when_volume_is_zero(self) -> None:
        audio = AQUARIUM.AmbientAudio(0, Path("/tmp"), water=True, bubbles=True)
        self.assertFalse(audio.start())
        self.assertEqual(audio.last_error, "volume is zero")
    def test_ambient_audio_synthesises_expected_channels(self) -> None:
        audio_water = AQUARIUM.AmbientAudio(100, Path("/tmp"), diagnostic=False, water=True, bubbles=False)
        self.assertTrue(audio_water.water)
        self.assertFalse(audio_water.bubbles)

        audio_bubbles = AQUARIUM.AmbientAudio(100, Path("/tmp"), diagnostic=False, water=False, bubbles=True)
        self.assertFalse(audio_bubbles.water)
        self.assertTrue(audio_bubbles.bubbles)




if __name__ == "__main__":
    unittest.main()
