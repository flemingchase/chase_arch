#!/usr/bin/env python3
"""Run an AUR helper's privileged command through an interactive su prompt.

Use with yay's --sudo option and --sudoloop=false. This adapter accepts a
command and its arguments, not sudo's authentication or configuration flags.
"""
import os
import shlex
import sys


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == '--':
        arguments.pop(0)
    if not arguments or not arguments[0] or arguments[0].startswith('-'):
        print('su_exec: expected a command; sudo options are not supported. '
              'Use yay with --sudoloop=false and no sudo flags.', file=sys.stderr)
        return 2
    if any('\0' in argument for argument in arguments):
        print('su_exec: command arguments cannot contain NUL bytes.', file=sys.stderr)
        return 2
    try:
        # Explicit POSIX sh matches shlex quoting even if root uses another shell.
        # Keep each original argument literal when su invokes the root shell.
        os.execv('/usr/bin/su', ['su', '--shell', '/bin/sh', '--command',
                                shlex.join(arguments)])
    except OSError as error:
        print(f'su_exec: could not start su: {error.strerror}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
