from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BackdropPickerTests(unittest.TestCase):
    def test_completion_marker_is_private_until_selection_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared"
            shared.mkdir(mode=0o1777)
            shared.chmod(0o1777)
            image = root / "reef.png"
            image.write_bytes(b"image contents")
            log = root / "picker-path"
            bin_dir = root / "bin"
            bin_dir.mkdir()
            chooser = bin_dir / "omarchy-shell"
            chooser.write_text(
                "#!/usr/bin/env bash\n"
                "stat -c '%a %n' -- \"$(dirname -- \"$7\")\" > \"$PICKER_TEST_LOG\"\n"
                "printf '%s\\n' \"$PICKER_TEST_IMAGE\" > \"$6\"\n"
                "touch -- \"$7\"\n",
                encoding="utf-8",
            )
            chooser.chmod(0o700)
            environment = os.environ.copy()
            environment.update({
                "HOME": str(root),
                "TMPDIR": str(shared),
                "PATH": str(bin_dir) + os.pathsep + environment["PATH"],
                "PICKER_TEST_IMAGE": str(image),
                "PICKER_TEST_LOG": str(log),
            })

            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "select-backdrop")],
                env=environment, capture_output=True, text=True, timeout=10,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, str(image) + "\n")
            mode, marker_dir = log.read_text(encoding="utf-8").strip().split(" ", 1)
            self.assertEqual(mode, "700")
            self.assertNotEqual(Path(marker_dir), shared)
            self.assertFalse(Path(marker_dir).exists())
            self.assertEqual(list(shared.iterdir()), [])
