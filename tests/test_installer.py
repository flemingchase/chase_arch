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
spec = importlib.util.spec_from_file_location('templates', ROOT / 'configs/install.py')
templates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(templates)


class InstallerTests(unittest.TestCase):
    def test_full_template_restore_is_repeatable(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(templates.main(['--home', str(home)]), 0)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(templates.main(['--home', str(home)]), 0)
            self.assertIn('Updated 0 files.', output.getvalue())
            self.assertTrue((home / '.config/qtile/wallpaper.jpg').is_file())
            self.assertTrue((home / '.xinitrc').is_file())
            self.assertTrue((home / '.xinitrc').stat().st_mode & 0o100)
            self.assertEqual((home / '.xinitrc').read_text(), '#!/bin/sh\nexec qtile start -b x11\n')
            self.assertTrue((home / '.local/bin/pcmanfm-themed').stat().st_mode & 0o100)
            self.assertIn(str(home), (home / '.local/share/applications/pcmanfm-qt.desktop').read_text())

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
            content = (ROOT / 'configs/.xinitrc').read_bytes()
            target.write_bytes(content)
            target.chmod(0o600)
            link = home / '.xinitrc'
            link.symlink_to(target)
            self.assertTrue(templates.save(link, content, 0o755))
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertFalse(templates.save(link, content, 0o755))
            target.write_text('old session')
            target.chmod(0o600)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(templates.save(link, content, 0o755))
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertEqual(len(list(home.glob('session.template-backup-*'))), 1)

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
        self.assertIn('git clone --depth 1', preview)
        self.assertIn('https://aur.archlinux.org/yay.git', preview)
        self.assertIn('makepkg --cleanbuild --clean --force', preview)
        self.assertIn('yay -S --needed -- clementine sioyek-git neovim-remote', preview)
        self.assertIn('enable ly@tty2.service', preview)
        self.assertIn('disable getty@tty2.service', preview)
        self.assertNotIn('--now', preview)
        self.assertNotIn('startx', preview)
        self.assertNotIn('xorg-xinit', preview)

    def test_no_aur_skips_helper_and_optional_packages(self):
        result = subprocess.run([sys.executable, str(ROOT / 'install.py'),
                                 '--packages-only', '--dry-run', '--no-aur'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('aur.archlinux.org/yay.git', result.stdout)
        self.assertNotIn('sioyek-git', result.stdout)
        self.assertIn('Skipped yay and optional AUR packages', result.stdout)

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

    def test_backup_repeat_and_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            original = home / 'original'
            original.write_text('old settings')
            link = home / '.vimrc'
            link.symlink_to(original)
            writes = templates.plan(ROOT / 'configs', home, home / '.config', home / '.local/share')
            target, content, mode = next(row for row in writes if row[0] == link)
            self.assertTrue(templates.save(target, content, mode))
            self.assertTrue(link.is_symlink())
            self.assertEqual(original.read_bytes(), content)
            backups = list(home.glob('original.template-backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), 'old settings')
            self.assertFalse(templates.save(target, content, mode))
            self.assertEqual(len(list(home.glob('original.template-backup-*'))), 1)

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
