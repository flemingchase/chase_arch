import contextlib
import importlib.util
import io
from pathlib import Path
import shlex
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('su_exec', ROOT / 'tools/su_exec.py')
su_exec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(su_exec)


class AurPrivilegeTests(unittest.TestCase):
    def test_arguments_remain_literal_in_root_shell_command(self):
        arguments = ['pacman', '-U', '--needed', '--',
                     '/tmp/a space/quote\' and "double".pkg.tar.zst',
                     '/tmp/$(unexpected);`command`\npackage.pkg.tar.zst']
        with patch.object(su_exec.os, 'execv') as execute:
            self.assertEqual(su_exec.main(arguments), 0)
        executable, command = execute.call_args.args
        self.assertEqual(executable, '/usr/bin/su')
        self.assertEqual(command[:4], ['su', '--shell', '/bin/sh', '--command'])
        self.assertEqual(shlex.split(command[4]), arguments)

    def test_optional_separator_is_not_passed_to_su(self):
        with patch.object(su_exec.os, 'execv') as execute:
            self.assertEqual(su_exec.main(['--', '/usr/bin/pacman', '-S', 'git']), 0)
        self.assertEqual(shlex.split(execute.call_args.args[1][-1]),
                         ['/usr/bin/pacman', '-S', 'git'])

    def test_missing_command_and_sudo_flags_fail_without_execution(self):
        for arguments in ([], ['--'], [''], ['-v'], ['-S', 'pacman'],
                          ['--preserve-env', 'pacman'], ['pacman', 'bad\0argument']):
            with self.subTest(arguments=arguments), \
                    patch.object(su_exec.os, 'execv') as execute, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(su_exec.main(arguments), 2)
                execute.assert_not_called()

    def test_unavailable_su_is_reported_without_traceback(self):
        with patch.object(su_exec.os, 'execv', side_effect=FileNotFoundError(2, 'No such file')), \
                contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(su_exec.main(['pacman', '-S', 'git']), 1)
        self.assertIn('could not start su', error.getvalue())


if __name__ == '__main__':
    unittest.main()
