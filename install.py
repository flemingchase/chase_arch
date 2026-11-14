#!/usr/bin/env python3
"""Install Chase's Qtile/X11 desktop and bundled template configurations."""
import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def packages(filename):
    result = []
    for line in filename.read_text().splitlines():
        name = line.partition('#')[0].strip()
        if not name:
            continue
        if not re.fullmatch(r'[a-z0-9][a-z0-9@._+\-]*', name):
            raise ValueError(f'Invalid package name in {filename}: {name!r}')
        if name not in result:
            result.append(name)
    if not result:
        raise ValueError(f'Empty package list: {filename}')
    return result


def run(command, dry_run):
    if command[0] == 'sudo' and (os.environ.get('CHASE_ARCH_PRIVILEGE') == 'su' or not shutil.which('sudo')):
        command = ['su', '-c', shlex.join(map(str, command[1:]))]
    print(('Would run: ' if dry_run else 'Running: ') + shlex.join(map(str, command)), flush=True)
    if not dry_run:
        subprocess.run(command, check=True)


def configure_ly(dry_run, display_manager=Path('/etc/systemd/system/display-manager.service')):
    # Disable the registered display manager without interrupting this session.
    if display_manager.is_symlink():
        current = display_manager.resolve().name
        if current != 'ly@tty2.service':
            run(['sudo', 'systemctl', 'disable', current], dry_run)
    # Ly and getty must not both manage the same virtual terminal.
    run(['sudo', 'systemctl', 'disable', 'getty@tty2.service'], dry_run)
    run(['sudo', 'systemctl', 'enable', 'ly@tty2.service'], dry_run)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing or installing anything')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--configs-only', action='store_true', help='Only restore bundled user configurations')
    mode.add_argument('--packages-only', action='store_true', help='Install packages and configure Ly without copying user settings')
    parser.add_argument('--home', type=Path, help='Staging home; requires --configs-only')
    parser.add_argument('--firefox-profile', type=Path, help='Existing Firefox profile for the optional overlay')
    parser.add_argument('--aur-helper', choices=('yay', 'paru'), help='Also install optional AUR packages using this existing helper')
    parser.add_argument('--enable-network', action='store_true', help='Enable NetworkManager for the next boot')
    parser.add_argument('--zsh', action='store_true', help='Change your login shell to /usr/bin/zsh')
    args = parser.parse_args(argv)
    if args.home is not None and not args.configs_only:
        parser.error('--home requires --configs-only')
    if args.configs_only and (args.aur_helper or args.enable_network or args.zsh):
        parser.error('--configs-only cannot be combined with system setup options')
    if args.packages_only and args.firefox_profile:
        parser.error('--firefox-profile cannot be combined with --packages-only')
    try:
        if not args.dry_run and os.geteuid() == 0:
            raise ValueError('Run as your normal desktop user, without sudo. Only package/system commands use sudo.')
        official = packages(ROOT / 'packages/official.txt') if not args.configs_only else []
        aur = packages(ROOT / 'packages/aur.txt') if args.aur_helper else []
        if not args.configs_only and not args.dry_run:
            release = Path('/etc/os-release').read_text().splitlines()
            if not any(line in ('ID=arch', 'ID="arch"') for line in release):
                raise ValueError('Package installation requires Arch Linux.')
            if Path('/run/archiso').exists():
                raise ValueError('Boot your installed Arch system first; do not run in the live installer.')
            for command in ('pacman', 'systemctl'):
                if not shutil.which(command):
                    raise ValueError(f'Missing {command}; complete the base-system prerequisites in README.md.')
            if not (shutil.which('sudo') or shutil.which('su')):
                raise ValueError('System changes require sudo or su with a root password.')
            if args.aur_helper and not shutil.which(args.aur_helper):
                raise ValueError(f'Install {args.aur_helper} first, or omit --aur-helper.')
        config_command = [sys.executable, str(ROOT / 'configs/install.py')]
        if args.home is not None:
            config_command += ['--home', str(args.home.expanduser().absolute())]
        if args.firefox_profile:
            config_command += ['--firefox-profile', str(args.firefox_profile.expanduser().absolute())]
        if not args.packages_only:
            # Validate destination layout before installing any packages or files.
            check = subprocess.run(config_command + ['--dry-run'], capture_output=True, text=True)
            if check.returncode:
                raise ValueError(check.stderr.strip())
        if official:
            # Full upgrade in the same transaction avoids Arch partial upgrades.
            run(['sudo', 'pacman', '-Syu', '--needed', '--', *official], args.dry_run)
        if aur:
            run([args.aur_helper, '-S', '--needed', '--', *aur], args.dry_run)
        if not args.packages_only:
            if args.dry_run:
                print(check.stdout, end='')
            else:
                run(config_command, False)
        if not args.configs_only:
            configure_ly(args.dry_run)
        if args.enable_network:
            run(['sudo', 'systemctl', 'enable', 'NetworkManager.service'], args.dry_run)
        if args.zsh:
            run(['chsh', '-s', '/usr/bin/zsh'], args.dry_run)
        if not args.aur_helper and not args.configs_only:
            print('Optional template applications not installed: see packages/aur.txt and --aur-helper.')
        if not args.configs_only:
            print('After a successful install, reboot and select the xinitrc session in Ly to launch Qtile.')
        print('Preview complete; nothing changed.' if args.dry_run else 'Installation complete.')
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'chase_arch: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
