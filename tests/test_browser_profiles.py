import contextlib
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import browser_profiles as profiles


class BrowserProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "home"
        self.config = self.home / ".config"

    def register(self, application="firefox", install=True, root=None):
        root = root or self.config / ("mozilla/firefox" if application == "firefox" else "librewolf/librewolf")
        root.mkdir(parents=True, exist_ok=True)
        legacy, dedicated = root / "legacy.default", root / "native.default-release"
        legacy.mkdir(exist_ok=True)
        dedicated.mkdir(exist_ok=True)
        text = "[Profile0]\nName=default\nPath=legacy.default\nIsRelative=1\nDefault=1\n"
        text += "[Profile1]\nName=default-release\nPath=native.default-release\nIsRelative=1\n"
        if install:
            text += "[InstallBUILD]\nDefault=native.default-release\nLocked=1\n"
        (root / "profiles.ini").write_text(text)
        return root, dedicated

    def test_fresh_plan_and_preview_never_write_or_launch(self):
        plans = profiles.plan_profiles(self.home, self.config)
        self.assertEqual([plan.application for plan in plans], ["firefox", "librewolf"])
        self.assertTrue(all(plan.create and plan.path is None for plan in plans))
        with patch.object(profiles, "_initialize") as initialize, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(profiles.prepare_profiles(plans, dry_run=True), {})
        initialize.assert_not_called()
        self.assertIn("Would initialize Firefox", out.getvalue())
        self.assertIn("Would initialize LibreWolf", out.getvalue())
        self.assertFalse(self.home.exists())

    def test_install_default_wins_over_legacy_default(self):
        root, dedicated = self.register()
        plan = profiles.plan_profiles(self.home, self.config, ["firefox"])[0]
        self.assertFalse(plan.create)
        self.assertEqual(plan.path, dedicated)
        with patch.object(profiles, "_initialize") as initialize:
            self.assertEqual(profiles.prepare_profiles([plan]), {"firefox": dedicated})
        initialize.assert_not_called()

    def test_installs_ini_and_absolute_profile_paths_are_supported(self):
        root, dedicated = self.register(install=False)
        (root / "installs.ini").write_text(f"[BUILD]\nDefault={dedicated}\nLocked=1\n")
        self.assertEqual(profiles.plan_profiles(self.home, self.config, ["firefox"])[0].path, dedicated)

    def test_legacy_librewolf_location_is_preferred(self):
        root, dedicated = self.register("librewolf", root=self.home / ".librewolf")
        self.register("librewolf")
        self.assertEqual(profiles.plan_profiles(self.home, self.config, ["librewolf"])[0].path, dedicated)

    def test_multiple_defaults_require_explicit_selection(self):
        root, dedicated = self.register()
        with (root / "profiles.ini").open("a") as stream:
            stream.write("[InstallOTHER]\nDefault=legacy.default\n")
        with self.assertRaisesRegex(ValueError, "--firefox-profile"):
            profiles.plan_profiles(self.home, self.config, ["firefox"])
        chosen = profiles.plan_profiles(self.home, self.config, ["firefox"], firefox_profile=dedicated)
        self.assertEqual(chosen[0].path, dedicated)

    def test_explicit_missing_profile_fails_without_writes(self):
        with self.assertRaisesRegex(ValueError, "must already exist"):
            profiles.plan_profiles(self.home, self.config, ["librewolf"], librewolf_profile=self.home / "missing")
        self.assertFalse(self.home.exists())

    def test_native_initialization_discovers_generated_profile_and_repeats_cleanly(self):
        plans = profiles.plan_profiles(self.home, self.config)
        initialized = []

        def initialize(command, environment):
            application = Path(command[0]).name
            initialized.append(application)
            self.assertEqual(environment["HOME"], str(self.home))
            self.assertEqual(environment["XDG_CONFIG_HOME"], str(self.config))
            self.assertEqual(environment["XDG_CACHE_HOME"], str(self.home / ".cache"))
            self.assertIn("--no-remote", command)
            self.assertIn("--headless", command)
            self.assertEqual(command[-1], "about:blank")
            self.register(application)

        with patch.object(profiles.shutil, "which", side_effect=lambda app: "/usr/bin/" + app), \
             patch.object(profiles, "_initialize", side_effect=initialize), \
             contextlib.redirect_stdout(io.StringIO()):
            ready = profiles.prepare_profiles(plans)
            repeated = profiles.prepare_profiles(profiles.plan_profiles(self.home, self.config))
        self.assertEqual(initialized, ["firefox", "librewolf"])
        self.assertEqual(ready, repeated)
        self.assertTrue(all(path.is_dir() for path in ready.values()))

    def test_missing_browser_and_failed_registration_are_reported(self):
        plan = profiles.plan_profiles(self.home, self.config, ["firefox"])[0]
        with patch.object(profiles.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "not installed"):
                profiles.prepare_profiles([plan])
        with patch.object(profiles.shutil, "which", return_value="/usr/bin/firefox"), \
             patch.object(profiles, "_initialize"), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "did not register"):
                profiles.prepare_profiles([plan])

    def test_profile_created_between_plan_and_prepare_is_not_opened(self):
        plan = profiles.plan_profiles(self.home, self.config, ["firefox"])[0]
        self.register()
        with patch.object(profiles.shutil, "which", return_value="/usr/bin/firefox"), \
             patch.object(profiles, "_initialize") as initialize:
            with self.assertRaisesRegex(ValueError, "changed after planning"):
                profiles.prepare_profiles([plan])
        initialize.assert_not_called()

    def test_timeout_only_terminates_the_owned_process_group(self):
        process = Mock(pid=43210)
        process.communicate.side_effect = [subprocess.TimeoutExpired("firefox", 60), ("", "")]
        with patch.object(profiles.subprocess, "Popen", return_value=process) as popen, \
             patch.object(profiles.os, "killpg") as kill:
            with self.assertRaisesRegex(ValueError, "Timed out"):
                profiles._initialize(["/usr/bin/firefox", "--headless"], {})
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        kill.assert_called_once_with(43210, signal.SIGTERM)

    def test_unlocked_persistent_lock_is_accepted_without_modification(self):
        root, dedicated = self.register()
        lock = dedicated / ".parentlock"
        lock.write_bytes(b"unchanged")
        before = lock.stat()
        # A stale +PID link must not block the installer when that PID has
        # since been reused by an unrelated running process.
        (dedicated / "lock").symlink_to(f"127.0.0.1:+{os.getpid()}")
        profiles.ensure_profiles_closed(profiles.plan_profiles(self.home, self.config, ["firefox"]))
        self.assertEqual(lock.read_bytes(), b"unchanged")
        self.assertEqual(lock.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertTrue((dedicated / "lock").is_symlink())

    def test_native_posix_lock_held_by_another_process_is_rejected(self):
        root, dedicated = self.register()
        lock = dedicated / ".parentlock"
        lock.touch()
        plans = profiles.plan_profiles(self.home, self.config, ["firefox"])
        source = "import fcntl,sys; f=open(sys.argv[1],'r+'); fcntl.lockf(f,fcntl.LOCK_EX); print('ready',flush=True); sys.stdin.read()"
        with subprocess.Popen([sys.executable, "-c", source, str(lock)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True) as holder:
            try:
                self.assertEqual(holder.stdout.readline().strip(), "ready")
                with self.assertRaisesRegex(ValueError, "Close Firefox"):
                    profiles.ensure_profiles_closed(plans)
                # A different staging profile is not blocked by this process.
                other = self.home / "staging-profile"
                other.mkdir()
                profiles.ensure_profiles_closed(profiles.plan_profiles(
                    self.home, self.config, ["firefox"], firefox_profile=other))
                self.assertFalse((other / ".parentlock").exists())
            finally:
                holder.communicate(timeout=5)
        profiles.ensure_profiles_closed(plans)

    def test_legacy_symlink_only_live_pid_is_rejected(self):
        root, dedicated = self.register("librewolf")
        symlink = dedicated / "lock"
        symlink.symlink_to(f"127.0.0.1:{os.getpid()}")
        plans = profiles.plan_profiles(self.home, self.config, ["librewolf"])
        with self.assertRaisesRegex(ValueError, "Close LibreWolf"):
            profiles.ensure_profiles_closed(plans)
        self.assertFalse((dedicated / ".parentlock").exists())
        self.assertTrue(symlink.is_symlink())

    def test_fresh_profile_lock_check_has_no_writes(self):
        profiles.ensure_profiles_closed(profiles.plan_profiles(self.home, self.config))
        self.assertFalse(self.home.exists())


if __name__ == "__main__":
    unittest.main()
