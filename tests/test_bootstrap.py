import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_installer import installer

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash')


def is_arch_linux():
    try:
        release = Path('/etc/os-release').read_text().splitlines()
    except OSError:
        return False
    return any(line in ('ID=arch', 'ID="arch"') for line in release)


ARCH_LINUX = is_arch_linux()


class BootstrapTests(unittest.TestCase):
    def script(self, path, body):
        path.write_text(f'#!{BASH}\nset -eu\n' + body)
        path.chmod(0o755)

    def environment(self, directory):
        directory = Path(directory)
        commands = directory / 'bin'
        commands.mkdir()
        environment = dict(os.environ, PATH=str(commands), LOG=str(directory / 'log'),
                           BIN=str(commands), FAKE_PYTHON=str(directory / 'python-launcher'))
        self.script(directory / 'python-launcher',
                    'printf "python: %s mode=%s\\n" "$*" "${CHASE_ARCH_PRIVILEGE:-}" >> "$LOG"\n')
        self.script(commands / 'pacman',
                    'printf "pacman: %s\\n" "$*" >> "$LOG"\n'
                    'if [[ $1 == -Q ]]; then exit 1; fi\n'
                    'if [[ ${FAIL_BOOTSTRAP:-0} == 1 ]]; then exit 42; fi\n'
                    '/usr/bin/ln -s "$FAKE_PYTHON" "$BIN/python3"\n')
        return commands, environment

    @unittest.skipIf(os.geteuid() == 0, 'The entry script intentionally refuses root installation')
    @unittest.skipUnless(ARCH_LINUX, 'The entry script intentionally rejects non-Arch hosts')
    def test_missing_python_is_installed_before_python_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            commands, environment = self.environment(directory)
            self.script(commands / 'sudo', 'if [[ $1 == -v ]]; then exit 0; fi\nexec "$@"\n')
            result = subprocess.run([BASH, str(ROOT / 'install.sh'), '--packages-only'],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            log = Path(environment['LOG']).read_text()
            self.assertIn('pacman: -Syu --needed -- python git', log)
            self.assertNotIn('base-devel', log)
            self.assertNotIn(' -- go', log)
            self.assertLess(log.index('pacman: -Syu'), log.index('python:'))
            self.assertIn('python: ./install.py --packages-only mode=sudo', log)

    @unittest.skipIf(os.geteuid() == 0, 'The entry script intentionally refuses root installation')
    @unittest.skipUnless(ARCH_LINUX, 'The entry script intentionally rejects non-Arch hosts')
    def test_base_only_system_uses_su_and_keeps_it_for_later_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            commands, environment = self.environment(directory)
            self.script(commands / 'su', 'printf "su: %s\\n" "$*" >> "$LOG"\n'
                        f'exec {shlex.quote(BASH)} "$@"\n')
            result = subprocess.run([BASH, str(ROOT / 'install.sh')],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            log = Path(environment['LOG']).read_text()
            self.assertIn('su: -c pacman -Syu --needed -- python git', log)
            self.assertIn('mode=su', log)

    @unittest.skipIf(os.geteuid() == 0, 'The entry script intentionally refuses root installation')
    @unittest.skipUnless(ARCH_LINUX, 'The entry script intentionally rejects non-Arch hosts')
    def test_bootstrap_failure_does_not_launch_python(self):
        with tempfile.TemporaryDirectory() as directory:
            commands, environment = self.environment(directory)
            environment['FAIL_BOOTSTRAP'] = '1'
            self.script(commands / 'sudo', 'if [[ $1 == -v ]]; then exit 0; fi\nexec "$@"\n')
            result = subprocess.run([BASH, str(ROOT / 'install.sh')],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 42, result.stderr)
            self.assertNotIn('python:', Path(environment['LOG']).read_text())

    def test_preview_and_help_without_python_make_no_changes(self):
        for argument in ('--dry-run', '--help'):
            with self.subTest(argument=argument), tempfile.TemporaryDirectory() as directory:
                _, environment = self.environment(directory)
                result = subprocess.run([BASH, str(ROOT / 'install.sh'), argument],
                                        env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(Path(environment['LOG']).exists())
                self.assertFalse((Path(environment['BIN']) / 'python3').exists())

    def test_list_apps_without_python_does_not_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            _, environment = self.environment(directory)
            result = subprocess.run([BASH, str(ROOT / 'install.sh'), '--list-apps'],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('--list-apps requires Python', result.stderr)
            self.assertFalse(Path(environment['LOG']).exists())
            self.assertFalse((Path(environment['BIN']) / 'python3').exists())

    def test_invalid_arguments_fail_before_python_or_privileged_commands(self):
        invalid = [
            ['--configs-only', '--packages-only'],
            ['--packages-only', '--configs-only'],
            ['--aur-helper', 'yay', '--no-aur'],
            ['--no-aur', '--aur-helper=paru'],
            ['--home', '/tmp/staging'],
            ['--dry-run', '--home=/tmp/staging'],
            ['--packages-only', '--firefox-profile', '/tmp/profile'],
            ['--packages-only', '--librewolf-profile=/tmp/profile'],
            ['--packages-only', '--offline-themes'],
            ['--packages-only', '--template-repo', '/tmp/templates'],
            ['--configs-only', '--aur-helper', 'yay'],
            ['--configs-only', '--no-aur'],
            ['--configs-only', '--enable-network'],
            ['--configs-only', '--zsh'],
            ['--configs-only', '--keep-shell'],
            ['--zsh', '--keep-shell'],
            ['--keep-shell', '--zsh'],
            ['--with', ',firefox'],
            ['--with', 'firefox,'],
            ['--with', 'firefox,,zathura'],
            ['--with', 'fire fox'],
            ['--with', 'firefox;uname'],
            ['--aur-helper', 'invalid'],
            ['--aur-helper=invalid'],
            ['--unknown'],
        ]
        for option in ('--home', '--firefox-profile', '--librewolf-profile', '--aur-helper', '--template-repo', '--with'):
            invalid.extend(([option], [option, ''], [option + '='], [option, '--dry-run']))
        for python_available in (False, True):
            for arguments in invalid:
                with self.subTest(python_available=python_available, arguments=arguments), \
                        tempfile.TemporaryDirectory() as directory:
                    commands, environment = self.environment(directory)
                    if python_available:
                        (commands / 'python3').symlink_to(environment['FAKE_PYTHON'])
                    for command in ('sudo', 'su'):
                        self.script(commands / command,
                                    'printf "unexpected privilege request\\n" >> "$LOG"\nexit 70\n')
                    result = subprocess.run([BASH, str(ROOT / 'install.sh'), *arguments],
                                            env=environment, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn('chase_arch:', result.stderr)
                    self.assertFalse(Path(environment['LOG']).exists())
                    self.assertEqual((commands / 'python3').exists(), python_available)

    def test_valid_profile_and_staging_arguments_reach_python_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            commands, environment = self.environment(directory)
            self.script(commands / 'python3', 'printf "<%s>\\n" "$@" >> "$LOG"\n')
            arguments = ['--configs-only', '--home', '/tmp/staging home',
                         '--firefox-profile=/tmp/firefox profile',
                         '--librewolf-profile', '/tmp/librewolf profile',
                         '--template-repo', '/tmp/template repository',
                         '--with', 'firefox, librewolf', '--with=chthm',
                         '--offline-themes', '--dry-run']
            result = subprocess.run([BASH, str(ROOT / 'install.sh'), *arguments],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(environment['LOG']).read_text().splitlines(),
                             ['<./install.py>', *[f'<{argument}>' for argument in arguments]])

    def test_valid_package_options_preview_without_python(self):
        for arguments in (['--aur-helper=paru'], ['--no-aur'], ['--packages-only'],
                          ['--with', 'zathura,firefox', '--keep-shell'],
                          ['--offline-themes', '--enable-network', '--zsh']):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as directory:
                commands, environment = self.environment(directory)
                result = subprocess.run([BASH, str(ROOT / 'install.sh'), '--dry-run', *arguments],
                                        env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Preview complete; nothing changed.', result.stdout)
                self.assertFalse(Path(environment['LOG']).exists())
                self.assertFalse((commands / 'python3').exists())

    def test_semantic_validation_failure_precedes_privilege_and_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            commands, environment = self.environment(directory)
            self.script(commands / 'python3',
                        'printf "python: %s\\n" "$*" >> "$LOG"\n'
                        'if [[ $2 == --validate-options ]]; then exit 2; fi\n'
                        'exit 77\n')
            for command in ('sudo', 'su'):
                self.script(commands / command,
                            'printf "unexpected privilege request\\n" >> "$LOG"\nexit 70\n')
            arguments = ['--with', 'unknown-app']
            result = subprocess.run([BASH, str(ROOT / 'install.sh'), *arguments],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(Path(environment['LOG']).read_text().splitlines(),
                             ['python: ./install.py --validate-options --with unknown-app'])

    def test_list_apps_with_python_delegates_without_system_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            commands, environment = self.environment(directory)
            self.script(commands / 'python3', 'printf "<%s>\\n" "$@" >> "$LOG"\n')
            result = subprocess.run([BASH, str(ROOT / 'install.sh'), '--list-apps'],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(environment['LOG']).read_text().splitlines(),
                             ['<./install.py>', '<--list-apps>'])

    def test_python_system_commands_use_selected_su_even_after_sudo_is_installed(self):
        with patch.dict(os.environ, {'CHASE_ARCH_PRIVILEGE': 'su'}), \
                patch.object(installer.subprocess, 'run') as run, \
                patch('builtins.print'):
            installer.run(['sudo', 'pacman', '-Syu', '--needed', '--', 'base-devel', 'python'], False)
        run.assert_called_once_with(
            ['su', '-c', 'pacman -Syu --needed -- base-devel python'], check=True)


if __name__ == '__main__':
    unittest.main()
