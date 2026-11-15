#!/usr/bin/env python3
"""Install the desktop, bundled application defaults, and chthm in one pass."""
import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib

from browser_profiles import ensure_profiles_closed, plan_profiles, prepare_profiles

ROOT = Path(__file__).resolve().parent
YAY_URL = 'https://aur.archlinux.org/yay.git'


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


def run(command, dry_run, cwd=None, env=None):
    if command[0] == 'sudo' and (os.environ.get('CHASE_ARCH_PRIVILEGE') == 'su' or not shutil.which('sudo')):
        command = ['su', '-c', shlex.join(map(str, command[1:]))]
    location = f' (in {cwd})' if cwd is not None else ''
    print(('Would run: ' if dry_run else 'Running: ') + shlex.join(map(str, command)) + location, flush=True)
    if not dry_run:
        options = {'check': True}
        if cwd is not None:
            options['cwd'] = cwd
        if env is not None:
            options['env'] = env
        subprocess.run(command, **options)


def target_environment(home=None):
    """Keep every user-level subprocess in the requested destination home."""
    env = os.environ.copy()
    if home is not None:
        home = home.expanduser().absolute()
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'),
                   XDG_DATA_HOME=str(home / '.local/share'),
                   XDG_STATE_HOME=str(home / '.local/state'),
                   XDG_CACHE_HOME=str(home / '.cache'), ZDOTDIR=str(home))
    return env


def user_paths(env):
    home = Path(env['HOME']).expanduser().absolute()
    config = Path(env.get('XDG_CONFIG_HOME') or home / '.config').expanduser().absolute()
    data = Path(env.get('XDG_DATA_HOME') or home / '.local/share').expanduser().absolute()
    return home, config, data


def validate_bundle():
    required = ['configs/install.py', 'configs/.xinitrc',
                'configs/firefox-profile/user.js', 'configs/librewolf-profile/user.js',
                'vendor/chthm/install.py', 'vendor/chthm/chthm.zsh',
                'vendor/chthm/src/chthm/cli.py', 'vendor/chthm/themes/gotham.toml',
                'vendor/chthm/themes/kimbie_dark.toml',
                'vendor/chthm/themes/alacritty-theme.LICENSE', 'tools/su_exec.py']
    for relative in required:
        if not (ROOT / relative).is_file():
            raise ValueError(f'Incomplete installer download: missing {relative}')
    for filename in (ROOT / 'vendor/chthm/themes').glob('*.toml'):
        colors = tomllib.loads(filename.read_text())['colors']['primary']
        if not all(re.fullmatch(r'#[0-9a-fA-F]{6}', colors[key])
                   for key in ('background', 'foreground')):
            raise ValueError(f'Invalid bundled palette: {filename.name}')


def template_command(home=None, profiles=None):
    command = [sys.executable, str(ROOT / 'configs/install.py')]
    if home is not None:
        command += ['--home', str(home.expanduser().absolute())]
    for application, profile in (profiles or {}).items():
        command += [f'--{application}-profile', str(profile)]
    return command


def install_chthm(env, profiles, dry_run, offline_themes=False):
    home, _, data = user_paths(env)
    source = ROOT / 'vendor/chthm'
    collection = data / 'chthm/themes'
    # Seed missing bundled themes first; Gotham remains available if the
    # optional upstream catalogue download fails. Existing custom themes stay.
    for filename in sorted((source / 'themes').iterdir()):
        destination = collection / filename.name
        if destination.exists():
            continue
        if dry_run:
            print(f'Would seed bundled theme: {destination}')
        else:
            collection.mkdir(parents=True, exist_ok=True)
            shutil.copy2(filename, destination)
    command = [sys.executable, str(source / 'install.py')]
    if offline_themes:
        command += ['--theme-source', str(source / 'themes')]
    run(command, dry_run, env=env)
    command = [str(home / '.local/bin/chthm'), 'gotham', '--no-reload']
    for application, profile in profiles.items():
        command += [f'--{application}-profile', str(profile)]
    run(command, dry_run, env=env)


def aur_command(helper, names):
    command = [helper]
    if os.environ.get('CHASE_ARCH_PRIVILEGE') == 'su' or not shutil.which('sudo'):
        command += ['--sudo', str(ROOT / 'tools/su_exec.py'), '--sudoflags=',
                    '--sudoloop=false' if helper == 'yay' else '--nosudoloop']
    return [*command, '-S', '--needed', '--', *names]


def install_yay(dry_run):
    """Build yay as the desktop user, then install the built package as root."""
    if shutil.which('yay'):
        print('Using installed AUR helper: yay')
        return
    if dry_run:
        staging = Path('/tmp/chase-arch-yay-build')
        print('Would install the default AUR helper: yay')
        run(['git', 'clone', '--depth', '1', '--', YAY_URL, staging / 'yay'], True)
        run(['makepkg', '--cleanbuild', '--clean', '--force'], True, cwd=staging / 'yay')
        run(['sudo', 'pacman', '-U', '--needed', '--', staging / 'yay/yay-PACKAGE.pkg.tar.zst'], True)
        return
    for command in ('git', 'makepkg'):
        if not shutil.which(command):
            raise ValueError(f'Missing {command}; the official package installation should provide yay build prerequisites.')
    with tempfile.TemporaryDirectory(prefix='chase-arch-yay-') as temporary:
        source = Path(temporary) / 'yay'
        run(['git', 'clone', '--depth', '1', '--', YAY_URL, source], False)
        run(['makepkg', '--cleanbuild', '--clean', '--force'], False, cwd=source)
        result = subprocess.run(['makepkg', '--packagelist'], cwd=source, check=True,
                                capture_output=True, text=True)
        listed = [Path(line) for line in result.stdout.splitlines()]
        built = [(path if path.is_absolute() else source / path) for path in listed
                 if path.name.startswith('yay-') and not path.name.startswith('yay-debug-')]
        if len(built) != 1 or not built[0].is_file():
            raise ValueError('Could not identify the yay package produced by makepkg.')
        run(['sudo', 'pacman', '-U', '--needed', '--', built[0]], False)


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
    mode.add_argument('--configs-only', action='store_true', help='Restore user configurations and install chthm without installing packages')
    mode.add_argument('--packages-only', action='store_true', help='Install packages and configure Ly without restoring settings or installing chthm')
    parser.add_argument('--home', type=Path, help='Staging home; requires --configs-only')
    parser.add_argument('--firefox-profile', type=Path, help='Choose an existing Firefox profile instead of discovering or initializing one')
    parser.add_argument('--librewolf-profile', type=Path, help='Choose an existing LibreWolf profile instead of discovering or initializing one')
    parser.add_argument('--offline-themes', action='store_true', help='Use bundled Gotham and Kimbie Dark themes without downloading the upstream catalogue')
    aur_mode = parser.add_mutually_exclusive_group()
    aur_mode.add_argument('--aur-helper', choices=('yay', 'paru'),
                          help='AUR helper to use; defaults to yay, which is installed when missing')
    aur_mode.add_argument('--no-aur', action='store_true', help='Skip yay and the optional AUR package list')
    parser.add_argument('--enable-network', action='store_true', help='Enable NetworkManager for the next boot')
    parser.add_argument('--zsh', action='store_true', help='Change your login shell to /usr/bin/zsh')
    args = parser.parse_args(argv)
    if args.home is not None and not args.configs_only:
        parser.error('--home requires --configs-only')
    if args.configs_only and (args.aur_helper or args.no_aur or args.enable_network or args.zsh):
        parser.error('--configs-only cannot be combined with system setup options')
    if args.packages_only and (args.firefox_profile or args.librewolf_profile or args.offline_themes):
        parser.error('Browser profile and theme options cannot be combined with --packages-only')
    try:
        if not args.dry_run and os.geteuid() == 0:
            raise ValueError('Run as your normal desktop user, without sudo. Only package/system commands use sudo.')
        validate_bundle()
        env = target_environment(args.home)
        home, config, _ = user_paths(env)
        official = packages(ROOT / 'packages/official.txt') if not args.configs_only else []
        aur_helper = args.aur_helper or 'yay'
        aur = packages(ROOT / 'packages/aur.txt') if not args.configs_only and not args.no_aur else []
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
            if aur_helper != 'yay' and not shutil.which(aur_helper):
                raise ValueError(f'Install {aur_helper} first, use the default yay helper, or pass --no-aur.')
        plans = []
        if not args.packages_only:
            applications = [name for name in ('firefox', 'librewolf')
                            if name in official or shutil.which(name)
                            or getattr(args, name + '_profile') is not None]
            plans = plan_profiles(home, config, applications=applications,
                                  firefox_profile=args.firefox_profile,
                                  librewolf_profile=args.librewolf_profile)
            if not args.dry_run:
                ensure_profiles_closed(plans)
            existing = {plan.application: plan.path for plan in plans if not plan.create}
            # Check the template and existing-profile destinations before packages.
            # Fresh profiles are initialized only after their browser is installed.
            check = subprocess.run(template_command(args.home, existing) + ['--dry-run'],
                                   capture_output=True, text=True, env=env)
            if check.returncode:
                raise ValueError(check.stderr.strip())
        if official:
            # Full upgrade in the same transaction avoids Arch partial upgrades.
            run(['sudo', 'pacman', '-Syu', '--needed', '--', *official], args.dry_run)
        if aur:
            if aur_helper == 'yay':
                install_yay(args.dry_run)
            run(aur_command(aur_helper, aur), args.dry_run)
        if not args.packages_only:
            profiles = prepare_profiles(plans, dry_run=args.dry_run, env=env)
            if args.dry_run:
                print(check.stdout, end='')
                for plan in plans:
                    if plan.create:
                        print(f'Would apply {plan.application} overlay to its newly initialized default profile')
            else:
                ready = plan_profiles(home, config, applications=list(profiles),
                                      firefox_profile=profiles.get('firefox'),
                                      librewolf_profile=profiles.get('librewolf'))
                ensure_profiles_closed(ready)
                run(template_command(args.home, profiles), False, env=env)
            install_chthm(env, profiles, args.dry_run, args.offline_themes)
        if not args.configs_only:
            configure_ly(args.dry_run)
        if args.enable_network:
            run(['sudo', 'systemctl', 'enable', 'NetworkManager.service'], args.dry_run)
        if args.zsh:
            run(['chsh', '-s', '/usr/bin/zsh'], args.dry_run)
        if args.no_aur:
            print('Skipped yay and optional AUR packages (--no-aur).')
        if not args.configs_only:
            print('After a successful install, reboot and select the xinitrc session in Ly to launch Qtile.')
        if not args.packages_only:
            print('Default theme: Gotham. After installation, open a new zsh terminal to use chthm shell integration.')
        print('Preview complete; nothing changed.' if args.dry_run else 'Installation complete.')
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f'chase_arch: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
