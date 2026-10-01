"""Deterministic coverage for scripts/idle-integration and the launch-decision
logic in scripts/launch-aquarium.

Every test runs against a disposable $HOME (never the live Omarchy state) and
never requires a running Hyprland session. scripts/launch-aquarium is
exercised end to end with a stubbed `xdg-terminal-exec` on PATH that exits
with a distinct sentinel code (42): reaching it proves the launch guard
decided to proceed, while an exit of 0 proves the guard suppressed the
launch. No production `--check`/dry-run flag is required for this.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDLE_INTEGRATION = ROOT / "scripts" / "idle-integration"
LAUNCH_AQUARIUM = ROOT / "scripts" / "launch-aquarium"

# scripts/launch-aquarium exits with this code only by reaching the stubbed
# xdg-terminal-exec below, i.e. only when the launch guard allowed it through.
PROCEED_SENTINEL = 42


def _toggle_path(home: Path) -> Path:
    return home / ".local" / "state" / "omarchy" / "toggles" / "screensaver-off"


def _owner_path(home: Path) -> Path:
    return home / ".local" / "state" / "omarcharium" / "owns-screensaver-off"


def _stay_awake_path(home: Path) -> Path:
    return home / ".local" / "state" / "omarchy" / "indicators" / "stay-awake"


class IdleIntegrationHelperTests(unittest.TestCase):
    """scripts/idle-integration: ownership lifecycle, races, and HOME semantics."""

    def run_helper(
        self, home: Path, action: str, *, check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["HOME"] = str(home)
        # Omarchy's own toggle store ignores XDG_STATE_HOME; make sure a
        # stray value in the test environment cannot change where the
        # helper looks either.
        environment["XDG_STATE_HOME"] = str(home / "unused-xdg-state-home")
        return subprocess.run(
            ["bash", str(IDLE_INTEGRATION), action],
            check=check,
            text=True,
            capture_output=True,
            env=environment,
        )

    def test_owned_stock_toggle_is_released(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.run_helper(home, "enable")
            toggle = _toggle_path(home)
            owner = _owner_path(home)
            self.assertTrue(toggle.exists())
            self.assertTrue(owner.exists())

            self.run_helper(home, "disable")
            self.assertFalse(toggle.exists())
            self.assertFalse(owner.exists())

    def test_ignores_xdg_state_home_and_follows_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.run_helper(home, "enable")

            self.assertTrue(_toggle_path(home).exists())
            self.assertFalse((home / "unused-xdg-state-home").exists())

    def test_legacy_empty_ownership_state_is_migrated_before_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            toggle = _toggle_path(home)
            owner = _owner_path(home)
            toggle.parent.mkdir(parents=True)
            owner.parent.mkdir(parents=True)
            toggle.touch()
            owner.touch()

            self.run_helper(home, "enable")
            status = self.run_helper(home, "status")

            self.assertGreater(toggle.stat().st_size, 0)
            self.assertEqual(toggle.read_bytes(), owner.read_bytes())
            self.assertEqual(status.stdout.strip(), "owned")
            self.run_helper(home, "disable")
            self.assertFalse(toggle.exists())
            self.assertFalse(owner.exists())

    def test_preexisting_user_toggle_is_never_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            toggle = _toggle_path(home)
            toggle.parent.mkdir(parents=True)
            toggle.touch()

            self.run_helper(home, "enable")
            self.run_helper(home, "disable")
            self.assertTrue(toggle.exists())
            self.assertFalse(_owner_path(home).exists())

    def test_replaced_toggle_is_not_mistaken_for_owned_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.run_helper(home, "enable")
            toggle = _toggle_path(home)
            owner = _owner_path(home)
            toggle.unlink()
            toggle.touch()

            self.run_helper(home, "disable")

            self.assertTrue(toggle.exists())
            self.assertFalse(owner.exists())

    def test_symlinked_owner_is_refused_without_modifying_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            owner = _owner_path(home)
            owner.parent.mkdir(parents=True)
            target = home / "target"
            target.write_text("preserve me", encoding="utf-8")
            owner.symlink_to(target)

            result = self.run_helper(home, "enable", check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "preserve me")
            self.assertFalse(_toggle_path(home).exists())

    def test_owned_state_is_private_and_reports_owned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.run_helper(home, "enable")
            toggle = _toggle_path(home)
            owner_dir = toggle.parents[2] / "omarcharium"
            owner = _owner_path(home)

            status = self.run_helper(home, "status")

            self.assertEqual(status.stdout.strip(), "owned")
            self.assertEqual(owner_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(toggle.stat().st_mode & 0o777, 0o600)
            self.assertEqual(owner.stat().st_mode & 0o777, 0o600)

    def test_lock_file_lives_inside_the_private_owner_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.run_helper(home, "enable")

            owner_dir = _owner_path(home).parent
            self.assertTrue((owner_dir / ".lock").exists())
            self.assertFalse((home / ".local" / "state" / ".omarcharium-idle.lock").exists())

    def test_symlinked_lock_file_is_refused_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            owner_dir = _owner_path(home).parent
            owner_dir.mkdir(parents=True)
            target = home / "target"
            target.write_text("preserve me", encoding="utf-8")
            (owner_dir / ".lock").symlink_to(target)

            result = self.run_helper(home, "enable", check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "preserve me")
            self.assertFalse(_toggle_path(home).exists())

    def test_orphaned_owner_is_reclaimed_after_toggle_removed_externally(self) -> None:
        # Regression for the bug where a second `enable` after only the
        # toggle disappeared (e.g. another tool cleared it) would fail
        # forever: it created a fresh toggle, failed to exclusively claim
        # the still-present owner record, deleted the toggle it just made,
        # and exited 1 -- leaving the owner orphaned permanently.
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.run_helper(home, "enable")
            toggle = _toggle_path(home)
            owner = _owner_path(home)
            self.assertTrue(toggle.exists())
            self.assertTrue(owner.exists())

            toggle.unlink()
            self.assertFalse(toggle.exists())
            self.assertTrue(owner.exists())

            result = self.run_helper(home, "enable", check=False)

            self.assertEqual(result.returncode, 0)
            self.assertTrue(toggle.exists())
            self.assertTrue(owner.exists())
            status = self.run_helper(home, "status")
            self.assertEqual(status.stdout.strip(), "owned")

            self.run_helper(home, "disable")
            self.assertFalse(toggle.exists())
            self.assertFalse(owner.exists())

    def test_foreign_toggle_with_unrelated_owner_record_is_never_claimed(self) -> None:
        # The toggle was replaced by something foreign while a stale
        # ownership record from a previous cycle still sits on disk. Because
        # a toggle is present, it must never be assumed to be ours.
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.run_helper(home, "enable")
            toggle = _toggle_path(home)
            owner = _owner_path(home)
            original_owner_marker = owner.read_bytes()

            toggle.unlink()
            toggle.write_text("someone-elses-marker", encoding="utf-8")

            result = self.run_helper(home, "enable", check=False)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(toggle.read_text(encoding="utf-8"), "someone-elses-marker")
            self.assertEqual(owner.read_bytes(), original_owner_marker)
            status = self.run_helper(home, "status")
            self.assertEqual(status.stdout.strip(), "user-disabled")

    def test_enable_failure_leaves_no_orphaned_ownership_record(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("permission enforcement is bypassed for root")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            toggle_dir = _toggle_path(home).parent
            toggle_dir.mkdir(parents=True)
            toggle_dir.chmod(0o500)
            try:
                result = self.run_helper(home, "enable", check=False)
            finally:
                toggle_dir.chmod(0o700)

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(_owner_path(home).exists())
            self.assertFalse(_toggle_path(home).exists())

    def test_concurrent_enable_calls_converge_on_consistent_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            results: list[subprocess.CompletedProcess[str]] = []

            def run() -> None:
                results.append(self.run_helper(home, "enable", check=False))

            threads = [threading.Thread(target=run) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            for result in results:
                self.assertEqual(result.returncode, 0)

            toggle = _toggle_path(home)
            owner = _owner_path(home)
            self.assertTrue(toggle.exists())
            self.assertTrue(owner.exists())
            self.assertEqual(toggle.read_bytes(), owner.read_bytes())
            status = self.run_helper(home, "status")
            self.assertEqual(status.stdout.strip(), "owned")


class LaunchAquariumDecisionTests(unittest.TestCase):
    """scripts/launch-aquarium: collision, Keep Awake, and toggle-ownership gating."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._stub_dir = tempfile.TemporaryDirectory()
        stub = Path(cls._stub_dir.name) / "xdg-terminal-exec"
        stub.write_text(f"#!/usr/bin/env bash\nexit {PROCEED_SENTINEL}\n", encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._stub_dir.cleanup()

    def run_launch(self, home: Path, mode: str, extra_path: Path | None = None) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["HOME"] = str(home)
        environment["XDG_STATE_HOME"] = str(home / "unused-xdg-state-home")
        environment["PATH"] = os.pathsep.join(
            str(path) for path in (extra_path, Path(self._stub_dir.name)) if path is not None
        ) + os.pathsep + environment.get("PATH", "")
        # Deterministic collision/session checks: no compositor to connect to.
        environment.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        environment.pop("XDG_RUNTIME_DIR", None)
        args = ["bash", str(LAUNCH_AQUARIUM)]
        if mode:
            args.append(mode)
        return subprocess.run(args, text=True, capture_output=True, env=environment)

    def enable_ownership(self, home: Path) -> None:
        environment = os.environ.copy()
        environment["HOME"] = str(home)
        subprocess.run(["bash", str(IDLE_INTEGRATION), "enable"], check=True, env=environment, capture_output=True)

    def test_force_proceeds_when_nothing_blocks_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_launch(Path(directory), "force")
            self.assertEqual(result.returncode, PROCEED_SENTINEL)

    def test_force_ignores_a_foreign_screensaver_off_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            toggle = _toggle_path(home)
            toggle.parent.mkdir(parents=True)
            toggle.write_text("user-owned", encoding="utf-8")

            result = self.run_launch(home, "force")
            self.assertEqual(result.returncode, PROCEED_SENTINEL)

    def test_automatic_is_suppressed_by_a_foreign_screensaver_off_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            toggle = _toggle_path(home)
            toggle.parent.mkdir(parents=True)
            toggle.write_text("user-owned", encoding="utf-8")

            result = self.run_launch(home, "automatic")
            self.assertEqual(result.returncode, 0)

    def test_bare_invocation_is_suppressed_by_a_foreign_screensaver_off_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            toggle = _toggle_path(home)
            toggle.parent.mkdir(parents=True)
            toggle.write_text("user-owned", encoding="utf-8")

            result = self.run_launch(home, "")
            self.assertEqual(result.returncode, 0)

    def test_automatic_requires_owned_suppression_even_when_stock_toggle_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_launch(Path(directory), "automatic")
            self.assertEqual(result.returncode, 0)

    def test_automatic_proceeds_when_toggle_is_omarcharium_owned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.enable_ownership(home)

            result = self.run_launch(home, "automatic")
            self.assertEqual(result.returncode, PROCEED_SENTINEL)

    def test_keep_awake_blocks_automatic_but_not_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            stay_awake = _stay_awake_path(home)
            stay_awake.parent.mkdir(parents=True)
            stay_awake.touch()

            automatic = self.run_launch(home, "automatic")
            self.assertEqual(automatic.returncode, 0)

            force = self.run_launch(home, "force")
            self.assertEqual(force.returncode, PROCEED_SENTINEL)

    def test_foreign_user_process_does_not_block_manual_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            bin_dir = home / "bin"
            bin_dir.mkdir()
            pgrep = bin_dir / "pgrep"
            pgrep.write_text(
                "#!/usr/bin/env bash\n"
                "# Model a foreign match for a global query, but no match for this UID.\n"
                "[[ \" $* \" != *\" -u \"* ]]\n",
                encoding="utf-8",
            )
            pgrep.chmod(0o755)

            result = self.run_launch(home, "force", bin_dir)
            self.assertEqual(result.returncode, PROCEED_SENTINEL)

    def test_existing_screensaver_process_blocks_any_mode(self) -> None:
        decoy = subprocess.Popen(
            ["bash", "-c", 'exec -a "decoy-org.omarchy.screensaver-marker" sleep 5'],
        )
        try:
            with tempfile.TemporaryDirectory() as directory:
                automatic = self.run_launch(Path(directory), "automatic")
                self.assertEqual(automatic.returncode, 0)

                force = self.run_launch(Path(directory), "force")
                self.assertEqual(force.returncode, 0)
        finally:
            decoy.terminate()
            decoy.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
