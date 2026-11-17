import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_installer import installer


@unittest.skipUnless(shutil.which('git'), 'Git is required for repository integration tests')
class TemplateRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / 'template source'
        self.repository.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Installer test')
        self.git('config', 'user.email', 'installer@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        files = {
            '.config/qtile/config.py': 'colors = {"primary": {"background": "#0a0f14", "foreground": "#98d1ce"}}\n',
            '.config/rofi/config.rasi': '* { background: #0a0f14; foreground: #98d1ce; }\n',
            '.config/qt6ct/qt6ct.conf': '[Appearance]\ncustom_palette=true\ncolor_scheme_path="colors/gotham.conf"\n',
            '.config/qt6ct/colors/gotham.conf': '[ColorScheme]\nactive_colors=#0a0f14,#98d1ce\n',
            'firefox-profile/user.js': '// test overlay\n',
            'librewolf-profile/user.js': '// test overlay\n',
            'version': 'first',
            'install.py': '''import argparse
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument('--home', type=Path, required=True)
parser.add_argument('--dry-run', action='store_true')
parser.add_argument('--components', required=True)
args = parser.parse_args()
source = Path(__file__).resolve().parent
if not args.dry_run:
    selected = args.components.split(',')
    for relative in ('qtile/config.py', 'rofi/config.rasi', 'qt6ct/qt6ct.conf', 'qt6ct/colors/gotham.conf'):
        if relative.split('/')[0] not in selected:
            continue
        destination = args.home / '.config' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source / '.config' / relative).read_bytes())
    (args.home / 'template-version').write_text((source / 'version').read_text())
    (args.home / 'template-components').write_text(args.components)
''',
        }
        for name, content in files.items():
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repository), *args],
                                       text=True, stderr=subprocess.STDOUT).strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'Test templates')

    def test_each_retrieval_uses_latest_commit_and_cleans_up(self):
        repository = self.repository.as_uri()
        with contextlib.redirect_stdout(io.StringIO()):
            with installer.retrieve_templates(repository) as first:
                self.assertEqual((first / 'version').read_text(), 'first')
                self.assertEqual(first.parent.parent, Path(tempfile.gettempdir()))
            self.assertFalse(first.parent.exists())
            (self.repository / 'version').write_text('second')
            self.commit()
            (self.repository / 'version').write_text('uncommitted')
            with installer.retrieve_templates(repository) as second:
                self.assertEqual((second / 'version').read_text(), 'second')
            self.assertFalse(second.parent.exists())

    def test_checkout_is_removed_after_installation_error(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'failed install'):
                with installer.retrieve_templates(self.repository.as_uri()) as source:
                    raise RuntimeError('failed install')
        self.assertFalse(source.parent.exists())

    def test_preview_does_not_clone_or_create_a_temporary_directory(self):
        with patch.object(installer.subprocess, 'run') as run, \
                patch.object(installer.tempfile, 'TemporaryDirectory') as temporary, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with installer.retrieve_templates(installer.TEMPLATE_REPOSITORY, dry_run=True):
                pass
        run.assert_not_called()
        temporary.assert_not_called()
        self.assertIn(installer.TEMPLATE_REPOSITORY, output.getvalue())

    def test_incomplete_repository_is_rejected_and_cleaned_up(self):
        (self.repository / 'install.py').unlink()
        self.commit()
        real_run = installer.run
        paths = []
        def run(command, *args, **kwargs):
            paths.append(command[-1])
            real_run(command, *args, **kwargs)
        with patch.object(installer, 'run', side_effect=run), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'missing install.py'):
                with installer.retrieve_templates(self.repository.as_uri()):
                    self.fail('Incomplete templates were accepted')
        self.assertFalse(paths[0].parent.exists())

    def test_clone_failure_stops_before_user_installation(self):
        home = self.root / 'destination'
        with patch.object(installer.os, 'geteuid', return_value=1000), \
                patch.object(installer, 'plan_profiles', return_value=[]), \
                patch.object(installer, 'install_chthm') as chthm, \
                patch.object(installer, 'install_session') as session, \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            result = installer.main(['--configs-only', '--home', str(home),
                                     '--template-repo', str(self.root / 'missing-repository')])
        self.assertEqual(result, 1)
        chthm.assert_not_called()
        session.assert_not_called()
        self.assertFalse(home.exists())

    def test_local_git_templates_install_with_bundled_chthm_in_isolated_home(self):
        home = self.root / 'destination'
        with patch.object(installer.os, 'geteuid', return_value=1000), \
                patch.object(installer, 'plan_profiles', return_value=[]), \
                contextlib.redirect_stdout(io.StringIO()):
            result = installer.main(['--configs-only', '--home', str(home),
                                     '--template-repo', self.repository.as_uri(), '--offline-themes'])
        self.assertEqual(result, 0)
        self.assertEqual((home / 'template-version').read_text(), 'first')
        self.assertTrue((home / '.xinitrc').stat().st_mode & 0o100)
        self.assertTrue((home / '.local/bin/chthm').is_file())
        self.assertIn('#0a0f14', (home / '.local/state/chthm/current.toml').read_text())
        self.assertIn('chthm()', (home / '.config/chthm/chthm.zsh').read_text())
        self.assertIn(str(home / '.config/chthm/chthm.zsh'), (home / '.zshrc').read_text())
        self.assertTrue((home / '.config/rofi/config.rasi').is_file())
        self.assertFalse((home / 'template_config').exists())

    def test_core_only_staging_includes_theme_defaults_without_optional_browser_templates(self):
        home = self.root / 'destination'
        # Optional browser overlays are not part of the required Git checkout.
        shutil.rmtree(self.repository / 'firefox-profile')
        shutil.rmtree(self.repository / 'librewolf-profile')
        self.commit()
        with patch.object(installer.os, 'geteuid', return_value=1000), \
                contextlib.redirect_stdout(io.StringIO()):
            result = installer.main(['--configs-only', '--home', str(home),
                                     '--template-repo', self.repository.as_uri(), '--offline-themes'])
        self.assertEqual(result, 0)
        self.assertEqual((home / 'template-version').read_text(), 'first')
        self.assertEqual(set((home / 'template-components').read_text().split(',')),
                         {'zsh', 'vim', 'qtile', 'alacritty', 'qutebrowser', 'rofi', 'qt6ct'})
        self.assertTrue((home / '.xinitrc').stat().st_mode & 0o100)
        self.assertTrue((home / '.local/bin/chthm').is_file())
        self.assertTrue((home / '.local/state/chthm/current.toml').is_file())
        self.assertTrue((home / '.config/qt6ct/qt6ct.conf').is_file())
        self.assertTrue((home / '.config/rofi/config.rasi').is_file())
        for application in ('firefox', 'librewolf', 'zathura', 'Clementine', 'sioyek', 'pcmanfm-qt'):
            self.assertFalse((home / '.config' / application).exists())


if __name__ == '__main__':
    unittest.main()
