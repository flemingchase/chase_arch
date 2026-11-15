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
            self.assertIn('pacman: -Syu --needed -- python base-devel', log)
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
            self.assertIn('su: -c pacman -Syu --needed -- python base-devel', log)
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

    def test_python_system_commands_use_selected_su_even_after_sudo_is_installed(self):
        with patch.dict(os.environ, {'CHASE_ARCH_PRIVILEGE': 'su'}), \
                patch.object(installer.subprocess, 'run') as run, \
                patch('builtins.print'):
            installer.run(['sudo', 'pacman', '-Syu', '--needed', '--', 'base-devel', 'python'], False)
        run.assert_called_once_with(
            ['su', '-c', 'pacman -Syu --needed -- base-devel python'], check=True)


if __name__ == '__main__':
    unittest.main()
