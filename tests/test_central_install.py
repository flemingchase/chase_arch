import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_installer import installer, ROOT


class CentralInstallTests(unittest.TestCase):
    def test_target_home_overrides_all_user_destinations(self):
        with patch.dict(os.environ, {key: '/outside' for key in (
                'HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME',
                'XDG_CACHE_HOME', 'ZDOTDIR')}):
            env = installer.target_environment(Path('/tmp/staging home'))
        home = Path('/tmp/staging home')
        self.assertEqual(installer.user_paths(env),
                         (home, home / '.config', home / '.local/share'))
        for key, relative in [('XDG_STATE_HOME', '.local/state'),
                              ('XDG_CACHE_HOME', '.cache'), ('ZDOTDIR', '')]:
            self.assertEqual(Path(env[key]), home / relative)

    def test_chthm_seed_install_and_selection_use_destination_without_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            env = installer.target_environment(home)
            profiles = {'firefox': home / 'ff', 'librewolf': home / 'lw'}
            with patch.object(installer, 'run') as run:
                installer.install_chthm(env, profiles, False, offline_themes=True,
                                        targets=('alacritty', 'qtile', 'firefox', 'librewolf'))
            theme = home / '.local/share/chthm/themes/gotham.toml'
            self.assertIn("#0a0f14", theme.read_text())
            self.assertTrue(theme.with_name('alacritty-theme.LICENSE').is_file())
            self.assertIn('--theme-source', run.call_args_list[0].args[0])
            selection = run.call_args_list[1].args[0]
            self.assertEqual(selection[:3], [str(home / '.local/bin/chthm'), 'gotham', '--no-reload'])
            self.assertIn(str(profiles['librewolf']), selection)
            self.assertEqual(selection[selection.index('--targets') + 1],
                             'alacritty,qtile,firefox,librewolf')
            self.assertTrue(all(call.kwargs['env'] == env for call in run.call_args_list))
            theme.write_text('existing customized palette')
            with patch.object(installer, 'run'):
                installer.install_chthm(env, profiles, False, offline_themes=True)
            self.assertEqual(theme.read_text(), 'existing customized palette')

    def test_chthm_preview_never_seeds_or_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'missing'
            with patch.object(installer.subprocess, 'run') as process, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                installer.install_chthm(installer.target_environment(home), {}, True)
            process.assert_not_called()
            self.assertFalse(home.exists())
            self.assertIn('gotham --no-reload', output.getvalue())

    def test_full_flow_installs_programs_before_profiles_configs_and_chthm(self):
        events = []
        source = Path('/tmp/fetched-template')
        @contextlib.contextmanager
        def retrieve(*args):
            events.append('retrieve')
            try:
                yield source
            finally:
                events.append('cleanup')
        def run(command, *args, **kwargs):
            if 'pacman' in command:
                events.append('packages')
            elif str(source / 'install.py') in command:
                events.append('configs')
        def prepare(*args, **kwargs):
            events.append('profiles')
            return {}
        read_text = Path.read_text
        def read(path, *args, **kwargs):
            return 'ID=arch\n' if str(path) == '/etc/os-release' else read_text(path, *args, **kwargs)
        with patch.object(installer.os, 'geteuid', return_value=1000), \
                patch.object(installer.shutil, 'which', side_effect=lambda name: '/usr/bin/' + name), \
                patch.object(Path, 'read_text', read), \
                patch.object(installer, 'plan_profiles', return_value=[]), \
                patch.object(installer, 'prepare_profiles', side_effect=prepare), \
                patch.object(installer, 'run', side_effect=run), \
                patch.object(installer, 'retrieve_templates', side_effect=retrieve), \
                patch.object(installer, 'install_session', side_effect=lambda *args: events.append('session')), \
                patch.object(installer, 'configure_ly'), \
                patch.object(installer, 'install_chthm', side_effect=lambda *args, **kwargs: events.append('chthm')), \
                patch.object(installer.subprocess, 'run', return_value=Mock(returncode=0, stdout='', stderr='')), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(['--no-aur', '--offline-themes']), 0)
        self.assertEqual(events, ['retrieve', 'packages', 'profiles', 'configs', 'session', 'chthm', 'cleanup'])

    def test_failed_template_preflight_prevents_package_work(self):
        original_read = Path.read_text
        def read(path, *args, **kwargs):
            return 'ID=arch\n' if str(path) == '/etc/os-release' else original_read(path, *args, **kwargs)
        with patch.object(installer.os, 'geteuid', return_value=1000), \
                patch.object(installer.shutil, 'which', side_effect=lambda name: '/usr/bin/' + name), \
                patch.object(Path, 'read_text', read), \
                patch.object(installer, 'plan_profiles', return_value=[]), \
                patch.object(installer, 'retrieve_templates', return_value=contextlib.nullcontext(Path('/tmp/fetched-template'))), \
                patch.object(installer.subprocess, 'run', return_value=Mock(returncode=1, stderr='invalid destination')), \
                patch.object(installer, 'run') as run, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(installer.main(['--no-aur']), 1)
        run.assert_not_called()

    def test_packages_only_never_runs_user_steps(self):
        with patch.object(installer, 'prepare_profiles') as profiles, \
                patch.object(installer, 'retrieve_templates') as retrieve, \
                patch.object(installer, 'install_session') as session, \
                patch.object(installer, 'install_chthm') as chthm, \
                patch.object(installer, 'run'), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(['--packages-only', '--no-aur', '--dry-run']), 0)
        profiles.assert_not_called()
        chthm.assert_not_called()
        retrieve.assert_not_called()
        session.assert_not_called()

    def test_default_configs_install_theme_switcher_but_ignore_unselected_installed_browsers(self):
        with patch.object(installer.shutil, 'which', side_effect=lambda name: '/usr/bin/' + name), \
                patch.object(installer, 'plan_profiles', return_value=[]) as profiles, \
                patch.object(installer, 'install_chthm') as chthm, \
                patch.object(installer, 'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(['--configs-only', '--dry-run']), 0)
        self.assertEqual(profiles.call_args.kwargs['applications'], [])
        chthm.assert_called_once()
        self.assertEqual(set(chthm.call_args.args[4]),
                         {'alacritty', 'qtile', 'qutebrowser', 'rofi', 'qt6ct'})
        template_commands = [call.args[0] for call in run.call_args_list
                             if '--components' in call.args[0]]
        self.assertTrue(template_commands)
        for command in template_commands:
            components = command[command.index('--components') + 1].split(',')
            self.assertEqual(set(components),
                             {'zsh', 'vim', 'qtile', 'alacritty', 'qutebrowser', 'rofi', 'qt6ct'})

    def test_only_selected_browser_is_planned_and_configuration_selected(self):
        with patch.object(installer.shutil, 'which', side_effect=lambda name: '/usr/bin/' + name), \
                patch.object(installer, 'plan_profiles', return_value=[]) as profiles, \
                patch.object(installer, 'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(['--configs-only', '--dry-run', '--with', 'firefox']), 0)
        self.assertEqual(profiles.call_args.kwargs['applications'], ['firefox'])
        commands = [call.args[0] for call in run.call_args_list if '--components' in call.args[0]]
        self.assertTrue(commands)
        for command in commands:
            components = command[command.index('--components') + 1].split(',')
            self.assertIn('firefox', components)
            self.assertNotIn('librewolf', components)

    def test_explicit_browser_profile_opts_in_without_detecting_other_browsers(self):
        with patch.object(installer.shutil, 'which', side_effect=lambda name: '/usr/bin/' + name), \
                patch.object(installer, 'plan_profiles', return_value=[]) as profiles, \
                patch.object(installer, 'run'), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(['--configs-only', '--dry-run',
                                             '--librewolf-profile', '/tmp/explicit-profile']), 0)
        self.assertEqual(profiles.call_args.kwargs['applications'], ['librewolf'])

    def test_configs_only_never_changes_login_shell(self):
        with patch.object(installer, 'plan_profiles', return_value=[]), \
                patch.object(installer, 'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(['--configs-only', '--dry-run']), 0)
        self.assertFalse(any(call.args[0][0] == 'chsh' for call in run.call_args_list))

    def test_su_options_match_each_aur_helper(self):
        with patch.dict(os.environ, {'CHASE_ARCH_PRIVILEGE': 'su'}):
            yay = installer.aur_command('yay', ['clementine'])
            paru = installer.aur_command('paru', ['clementine'])
        self.assertIn('--sudoloop=false', yay)
        self.assertIn('--nosudoloop', paru)
        for command in (yay, paru):
            self.assertIn('--sudoflags=', command)
            self.assertEqual(command[-4:], ['-S', '--needed', '--', 'clementine'])


if __name__ == '__main__':
    unittest.main()
