import importlib.util
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_dry_run_has_no_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'home'
            result = subprocess.run([sys.executable, str(ROOT / 'install.py'),
                                     '--configs-only', '--dry-run', '--home', str(home)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('.xinitrc', result.stdout)
            self.assertNotIn('systemctl', result.stdout)
            self.assertFalse(home.exists())

    def test_xinitrc_repairs_execute_permission_even_through_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = home / 'session'
            content = (ROOT / 'session/xinitrc').read_bytes()
            target.write_bytes(content)
            target.chmod(0o600)
            link = home / '.xinitrc'
            link.symlink_to(target)
            self.assertTrue(installer.install_session(installer.target_environment(home)))
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertFalse(installer.install_session(installer.target_environment(home)))
            target.write_text('old session')
            target.chmod(0o600)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(installer.install_session(installer.target_environment(home)))
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertEqual(len(list(home.glob('session.chase-arch-backup-*'))), 1)

    def test_ly_disables_previous_manager_and_getty_before_enabling(self):
        with tempfile.TemporaryDirectory() as temporary:
            display_manager = Path(temporary) / 'display-manager.service'
            display_manager.symlink_to('/usr/lib/systemd/system/lightdm.service')
            with patch.object(installer, 'run') as run:
                installer.configure_ly(True, display_manager)
            self.assertEqual([call.args for call in run.call_args_list], [
                (['sudo', 'systemctl', 'disable', 'lightdm.service'], True),
                (['sudo', 'systemctl', 'disable', 'getty@tty2.service'], True),
                (['sudo', 'systemctl', 'enable', 'ly@tty2.service'], True),
            ])

    def test_package_preview_enables_ly_without_starting_services(self):
        with patch.object(installer.shutil, 'which', return_value=None), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(installer.main(['--packages-only', '--dry-run']), 0)
        preview = output.getvalue()
        self.assertNotIn('git clone', preview)
        self.assertNotIn('makepkg', preview)
        self.assertNotIn('neovim-remote', preview)
        self.assertNotIn('clementine', preview)
        self.assertNotIn('sioyek', preview)
        self.assertNotIn('base-devel', preview)
        self.assertNotIn('firefox', preview)
        self.assertNotIn('librewolf', preview)
        self.assertIn('enable ly@tty2.service', preview)
        self.assertIn('disable getty@tty2.service', preview)
        self.assertNotIn('--now', preview)
        self.assertNotIn('startx', preview)
        self.assertNotIn('xorg-xinit', preview)

    def test_no_aur_core_install_never_bootstraps_a_helper(self):
        result = subprocess.run([sys.executable, str(ROOT / 'install.py'),
                                 '--packages-only', '--dry-run', '--no-aur'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('aur.archlinux.org/yay.git', result.stdout)
        self.assertNotIn('neovim-remote', result.stdout)

    def test_selected_aur_module_previews_build_tools_and_helper(self):
        with patch.object(installer.shutil, 'which', return_value=None), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(installer.main(['--packages-only', '--with', 'neovim-remote', '--dry-run']), 0)
        preview = output.getvalue()
        self.assertIn('https://aur.archlinux.org/yay.git', preview)
        self.assertIn('makepkg --cleanbuild --clean --force', preview)
        self.assertIn('-S --needed -- neovim-remote', preview)
        self.assertIn('base-devel', preview)
        self.assertIn('tools/su_exec.py', preview)
        self.assertIn('--sudoloop=false', preview)

    def test_zsh_is_default_login_shell_with_keep_shell_opt_out(self):
        for extra, changes_shell in (([], True), (['--keep-shell'], False)):
            with self.subTest(extra=extra), patch.object(installer, 'run') as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(installer.main(['--packages-only', '--dry-run', *extra]), 0)
            shell_calls = [call for call in run.call_args_list if call.args[0][0] == 'chsh']
            self.assertEqual(bool(shell_calls), changes_shell)
            if shell_calls:
                self.assertEqual(shell_calls[0].args[0], ['chsh', '-s', '/usr/bin/zsh'])

    def test_enable_network_selects_networkmanager_and_enables_only_future_boots(self):
        with patch.object(installer, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(['--packages-only', '--dry-run', '--enable-network']), 0)
        commands = [call.args[0] for call in run.call_args_list]
        package_command = next(command for command in commands if 'pacman' in command)
        self.assertIn('networkmanager', package_command)
        network_command = next(command for command in commands if 'NetworkManager.service' in command)
        self.assertEqual(network_command, ['sudo', 'systemctl', 'enable', 'NetworkManager.service'])
        self.assertNotIn('--now', network_command)

    def test_unknown_optional_app_fails_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'missing'
            result = subprocess.run([sys.executable, str(ROOT / 'install.py'), '--configs-only',
                                     '--home', str(home), '--with', 'unknown-app'],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unknown optional applications', result.stderr)
            self.assertNotIn('git clone', result.stdout)
            self.assertNotIn('pacman', result.stdout)
            self.assertFalse(home.exists())

    def test_no_aur_rejects_requested_aur_application(self):
        result = subprocess.run([sys.executable, str(ROOT / 'install.py'), '--packages-only',
                                 '--dry-run', '--no-aur', '--with', 'clementine'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--no-aur conflicts', result.stderr)
        self.assertNotIn('pacman', result.stdout)

    def test_catalog_and_validation_modes_do_not_start_installation(self):
        for arguments in (['--list-apps'], ['--validate-options', '--with', 'zathura,firefox']):
            with self.subTest(arguments=arguments), \
                    patch.object(installer, 'validate_bundle') as validate, \
                    patch.object(installer, 'plan_profiles') as profiles, \
                    patch.object(installer, 'retrieve_templates') as retrieve, \
                    patch.object(installer, 'run') as run, \
                    patch.object(installer.os, 'geteuid', return_value=0), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(installer.main(arguments), 0)
            validate.assert_not_called()
            profiles.assert_not_called()
            retrieve.assert_not_called()
            run.assert_not_called()
            if arguments == ['--list-apps']:
                self.assertIn('Required:', output.getvalue())
                self.assertIn('zathura', output.getvalue())
            else:
                self.assertEqual(output.getvalue(), '')

    def test_yay_build_is_installed_with_selected_privilege_method(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / 'yay-12.0.0-1-x86_64.pkg.tar.zst'
            package.touch()
            package_list = Mock(stdout=str(package) + '\n')
            with patch.object(installer.shutil, 'which',
                              side_effect=lambda name: None if name == 'yay' else f'/usr/bin/{name}'), \
                    patch.object(installer.tempfile, 'TemporaryDirectory') as temporary_directory, \
                    patch.object(installer, 'run') as run, \
                    patch.object(installer.subprocess, 'run', return_value=package_list) as subprocess_run:
                temporary_directory.return_value.__enter__.return_value = temporary
                installer.install_yay(False)
        source = Path(temporary) / 'yay'
        self.assertEqual([call.args for call in run.call_args_list], [
            (['git', 'clone', '--depth', '1', '--', installer.YAY_URL, source], False),
            (['makepkg', '--cleanbuild', '--clean', '--force'], False),
            (['sudo', 'pacman', '-U', '--needed', '--', package], False),
        ])
        self.assertEqual(run.call_args_list[1].kwargs, {'cwd': source})
        subprocess_run.assert_called_once_with(['makepkg', '--packagelist'], cwd=source, check=True,
                                               capture_output=True, text=True)

    def test_invalid_profile_fails_before_package_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, str(ROOT / 'install.py'), '--dry-run',
                                     '--firefox-profile', str(Path(temporary) / 'missing')],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('pacman', result.stdout)

    def test_package_list_rejects_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / 'packages.txt'
            manifest.write_text('--noconfirm\n')
            with self.assertRaises(ValueError):
                installer.packages(manifest)


if __name__ == '__main__':
    unittest.main()
