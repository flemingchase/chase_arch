#!/usr/bin/env python3
"""Install the desktop, Git-hosted application defaults, and bundled chthm."""
import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import uuid

from browser_profiles import ensure_profiles_closed, plan_profiles, prepare_profiles
from app_modules import CORE_APPS, packages, print_catalog, resolve_selection

ROOT = Path(__file__).resolve().parent
YAY_URL = 'https://aur.archlinux.org/yay.git'
TEMPLATE_REPOSITORY = 'https://github.com/flemingchase/template_config.git'


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


def validate_bundle(include_chthm=True):
    required = ['session/xinitrc', 'tools/su_exec.py']
    if include_chthm:
        required += ['vendor/chthm/install.py', 'vendor/chthm/chthm.zsh',
                'vendor/chthm/src/chthm/cli.py', 'vendor/chthm/themes/gotham.toml',
                'vendor/chthm/themes/kimbie_dark.toml',
                'vendor/chthm/themes/alacritty-theme.LICENSE']
    for relative in required:
        if not (ROOT / relative).is_file():
            raise ValueError(f'Incomplete installer download: missing {relative}')
    for filename in (ROOT / 'vendor/chthm/themes').glob('*.toml') if include_chthm else ():
        colors = tomllib.loads(filename.read_text())['colors']['primary']
        if not all(re.fullmatch(r'#[0-9a-fA-F]{6}', colors[key])
                   for key in ('background', 'foreground')):
            raise ValueError(f'Invalid bundled palette: {filename.name}')


@contextmanager
def retrieve_templates(repository, dry_run=False):
    """Use a fresh default-branch checkout per run; never keep it in this repo."""
    def clone(source):
        run(['git', 'clone', '--depth', '1', '--single-branch', '--', repository, source], dry_run)

    if dry_run:
        source = Path('/tmp/chase-arch-templates-PREVIEW/template_config')
        clone(source)
        yield source
        return
    if not shutil.which('git'):
        raise ValueError('Git is required to retrieve template_config. Install git first.')
    with tempfile.TemporaryDirectory(prefix='chase-arch-templates-') as directory:
        source = Path(directory) / 'template_config'
        clone(source)
        for relative in ('install.py', '.config/qtile/config.py'):
            if not (source / relative).is_file():
                raise ValueError(f'Incomplete template_config repository: missing {relative}')
        revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                                           text=True).strip()
        print(f'Template revision: {revision}', flush=True)
        yield source


def template_command(source, home=None, profiles=None, components=None):
    command = [sys.executable, str(source / 'install.py')]
    if components is not None:
        command += ['--components', ','.join(components)]
    if home is not None:
        command += ['--home', str(home.expanduser().absolute())]
    for application, profile in (profiles or {}).items():
        command += [f'--{application}-profile', str(profile)]
    return command


def install_session(env, dry_run=False):
    """Install chase_arch's own X11 launcher, preserving links and backups."""
    home, _, _ = user_paths(env)
    destination = home / '.xinitrc'
    if dry_run:
        print(f'Would install Qtile session: {destination}')
        return False
    destination = destination.resolve()
    content = (ROOT / 'session/xinitrc').read_bytes()
    mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else 0o755
    if destination.exists() and destination.read_bytes() == content:
        if not mode & stat.S_IXUSR:
            destination.chmod(mode | stat.S_IXUSR)
            return True
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.chase-arch-session-', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode | stat.S_IXUSR)
        if destination.exists():
            suffix = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
            backup = destination.with_name(destination.name + '.chase-arch-backup-' + suffix)
            shutil.copy2(destination, backup)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f'Installed Qtile session: {destination}')
    return True


def install_chthm(env, profiles, dry_run, offline_themes=False, targets=None):
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
    if targets is not None:
        command += ['--targets', ','.join(targets)]
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
    mode.add_argument('--configs-only', action='store_true', help='Restore selected user configurations and install chthm without installing packages')
    mode.add_argument('--packages-only', action='store_true', help='Install packages and configure Ly without restoring settings or installing chthm')
    parser.add_argument('--home', type=Path, help='Staging home; requires --configs-only')
    parser.add_argument('--template-repo', help='Template Git URL or local Git repository; defaults to ' + TEMPLATE_REPOSITORY)
    parser.add_argument('--with', dest='with_apps', action='append', default=[], metavar='APPS',
                        help='Add optional applications, comma-separated; repeatable (see --list-apps)')
    parser.add_argument('--list-apps', action='store_true', help='List required and optional applications without changes')
    parser.add_argument('--validate-options', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--firefox-profile', type=Path, help='Choose an existing Firefox profile instead of discovering or initializing one')
    parser.add_argument('--librewolf-profile', type=Path, help='Choose an existing LibreWolf profile instead of discovering or initializing one')
    parser.add_argument('--offline-themes', action='store_true', help='Use bundled themes without downloading the upstream catalogue')
    aur_mode = parser.add_mutually_exclusive_group()
    aur_mode.add_argument('--aur-helper', choices=('yay', 'paru'),
                          help='Helper for selected AUR applications; yay is installed only when needed')
    aur_mode.add_argument('--no-aur', action='store_true', help='Reject selections requiring AUR packages')
    parser.add_argument('--enable-network', action='store_true', help='Select NetworkManager and enable it for the next boot')
    shell = parser.add_mutually_exclusive_group()
    shell.add_argument('--zsh', action='store_true', help='Use zsh as login shell (already the default for system installs)')
    shell.add_argument('--keep-shell', action='store_true', help='Keep the current login shell while installing zsh')
    args = parser.parse_args(argv)
    if args.home is not None and not args.configs_only:
        parser.error('--home requires --configs-only')
    if args.configs_only and (args.aur_helper or args.no_aur or args.enable_network or args.zsh or args.keep_shell):
        parser.error('--configs-only cannot be combined with system setup options')
    if args.template_repo is not None and not args.template_repo.strip():
        parser.error('--template-repo requires a nonempty URL or Git repository path')
    if args.packages_only and (args.firefox_profile or args.librewolf_profile or args.offline_themes or args.template_repo):
        parser.error('Browser profile, template and theme options cannot be combined with --packages-only')
    requested = list(args.with_apps)
    for application in ('firefox', 'librewolf'):
        if getattr(args, application + '_profile') is not None:
            requested.append(application)
    if args.enable_network:
        requested.append('networkmanager')
    try:
        selection = resolve_selection(requested, no_aur=args.no_aur, aur_helper=args.aur_helper or 'yay')
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.validate_options:
        return 0
    if args.list_apps:
        print_catalog()
        return 0
    try:
        with ExitStack() as resources:
            if not args.dry_run and os.geteuid() == 0:
                raise ValueError('Run as your normal desktop user, without sudo. Only package/system commands use sudo.')
            validate_bundle(include_chthm=not args.packages_only)
            env = target_environment(args.home)
            home, config, _ = user_paths(env)
            official = list(selection.official) if not args.configs_only else []
            aur_helper = args.aur_helper or 'yay'
            aur = list(selection.aur) if not args.configs_only else []
            print('Required applications: ' + ', '.join(CORE_APPS))
            print('Optional applications: ' + (', '.join(selection.optional) or 'none'))
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
                if aur and aur_helper != 'yay' and not shutil.which(aur_helper):
                    raise ValueError(f'Install {aur_helper} first, use the default yay helper, or pass --no-aur.')
            plans = []
            if not args.packages_only:
                applications = [name for name in ('firefox', 'librewolf')
                                if name in selection.optional]
                plans = plan_profiles(home, config, applications=applications,
                                      firefox_profile=args.firefox_profile,
                                      librewolf_profile=args.librewolf_profile)
                if not args.dry_run:
                    ensure_profiles_closed(plans)
                existing = {plan.application: plan.path for plan in plans if not plan.create}
                source = resources.enter_context(retrieve_templates(
                    args.template_repo or TEMPLATE_REPOSITORY, args.dry_run))
                # Validate fetched templates before the main package transaction.
                # A preview does not fetch or execute remote code.
                if args.dry_run:
                    run(template_command(source, args.home, existing, selection.components) + ['--dry-run'], True, env=env)
                    print('Template destinations will be validated after retrieval during installation.')
                else:
                    check = subprocess.run(template_command(source, args.home, existing, selection.components) + ['--dry-run'],
                                           capture_output=True, text=True, env=env)
                    if check.returncode:
                        raise ValueError((check.stderr.strip() or check.stdout.strip() or 'Template preflight failed')
                                         + '\nThe template repository must support --components; publish its modular installer before using this version.')
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
                    run(template_command(source, args.home, profiles, selection.components), True, env=env)
                    for plan in plans:
                        if plan.create:
                            print(f'Would apply {plan.application} overlay to its newly initialized default profile')
                else:
                    ready = plan_profiles(home, config, applications=list(profiles),
                                          firefox_profile=profiles.get('firefox'),
                                          librewolf_profile=profiles.get('librewolf'))
                    ensure_profiles_closed(ready)
                    run(template_command(source, args.home, profiles, selection.components), False, env=env)
                install_session(env, args.dry_run)
                install_chthm(env, profiles, args.dry_run, args.offline_themes, selection.targets)
            if not args.configs_only:
                configure_ly(args.dry_run)
            if args.enable_network:
                run(['sudo', 'systemctl', 'enable', 'NetworkManager.service'], args.dry_run)
            if not args.configs_only and not args.keep_shell:
                run(['chsh', '-s', '/usr/bin/zsh'], args.dry_run)
            if args.no_aur:
                print('AUR packages are disabled (--no-aur).')
            if not args.configs_only:
                print('After a successful install, reboot and select the xinitrc session in Ly to launch Qtile.')
            if not args.packages_only:
                print('Default template palette: Gotham.')
                print('Open a new zsh terminal to use chthm shell integration.')
            print('Preview complete; nothing changed.' if args.dry_run else 'Installation complete.')
            return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f'chase_arch: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
