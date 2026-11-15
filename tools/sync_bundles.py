#!/usr/bin/env python3
"""Refresh committed upstream snapshots for the self-contained installer."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile
import os
import tomllib

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.github', '__pycache__', '.git'}


def git(source, *arguments):
    return subprocess.check_output(['git', '-C', str(source), *arguments])


def snapshot(source):
    """Read HEAD blobs, not local caches, credentials or uncommitted files."""
    source = source.expanduser().resolve()
    if Path(git(source, 'rev-parse', '--show-toplevel').decode().strip()) != source:
        raise ValueError(f'Choose the root of a source Git repository: {source}')
    commit = git(source, 'rev-parse', 'HEAD').decode().strip()
    result = {}
    entries = git(source, 'ls-tree', '-rz', '--full-tree', commit).split(b'\0')
    process = subprocess.Popen(['git', '-C', str(source), 'cat-file', '--batch'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for entry in entries:
            if not entry:
                continue
            metadata, raw_path = entry.split(b'\t', 1)
            mode, kind, oid = metadata.decode().split()
            path = PurePosixPath(raw_path.decode())
            if path.is_absolute() or '..' in path.parts:
                raise ValueError(f'Unsafe source path: {path}')
            if any(part in IGNORED for part in path.parts) or path.suffix in ('.pyc', '.pyo'):
                continue
            if kind != 'blob' or mode not in ('100644', '100755'):
                raise ValueError(f'Bundle sources must be regular files: {path}')
            process.stdin.write((oid + '\n').encode())
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[1] != b'blob':
                raise ValueError(f'Could not read source blob: {path}')
            content = process.stdout.read(int(header[2]))
            process.stdout.read(1)
            result[str(path)] = (content, int(mode[-3:], 8))
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait()
    if process.returncode:
        raise ValueError('Reading source Git objects failed')
    return commit, result


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('The upstream template installer changed; review the .xinitrc adapter')
    return text.replace(before, after, 1)


def template_installer(content):
    """Keep the small Arch session extension explicit when refreshing upstream."""
    text = content.decode()
    text = replace_once(text, "for name, destination in (('.vimrc', home / '.vimrc'),",
                        "for name, destination in (('.xinitrc', home / '.xinitrc'), ('.vimrc', home / '.vimrc'),")
    text = replace_once(text, 'def save(filename, content, mode):\n    filename = filename.resolve()',
                        "def save(filename, content, mode):\n    executable = filename.name in ('.xinitrc', 'pcmanfm-themed')\n    filename = filename.resolve()")
    text = replace_once(text, 'if filename.exists() and filename.read_bytes() == content:\n        return False',
                        'if filename.exists() and filename.read_bytes() == content:\n        if executable and not filename.stat().st_mode & stat.S_IXUSR:\n            filename.chmod(stat.S_IMODE(filename.stat().st_mode) | stat.S_IXUSR)\n            return True\n        return False')
    text = replace_once(text, "if filename.name == 'pcmanfm-themed':\n        mode |= 0o100  # An existing wrapper must remain executable after replacement.",
                        'if executable:\n        mode |= stat.S_IXUSR')
    compile(text, 'configs/install.py', 'exec')
    return text.encode()


def digest(files):
    checksum = hashlib.sha256()
    for name, (content, mode) in sorted(files.items()):
        checksum.update(name.encode() + b'\0' + str(mode).encode() + b'\0')
        checksum.update(hashlib.sha256(content).digest())
    return checksum.hexdigest()


def ensure_safe_destination(path):
    if not path.is_relative_to(ROOT):
        raise ValueError(f'Destination is outside this repository: {path}')
    for parent in (path, *path.parents):
        if parent == ROOT:
            break
        if parent.is_symlink():
            raise ValueError(f'Refusing a symlink in the bundle destination: {parent}')


def publish(files, check=False, dry_run=False):
    """Replace managed files only; refuse to delete unknown local material."""
    tracked = set(git(ROOT, 'ls-files', '-z', '--', 'configs', 'vendor/chthm').decode().split('\0'))
    ignored = set(git(ROOT, 'ls-files', '--others', '--ignored', '--exclude-standard',
                      '-z', '--', 'configs', 'vendor/chthm').decode().split('\0'))
    old_manifest = ROOT / 'bundles.json'
    if old_manifest.exists():
        tracked.update(json.loads(old_manifest.read_text()).get('files', []))
    changes, removals = [], []
    for prefix in ('configs', 'vendor/chthm'):
        directory = ROOT / prefix
        ensure_safe_destination(directory)
        for path in directory.rglob('*'):
            ensure_safe_destination(path)
            if path.is_dir():
                continue
            relative = path.relative_to(ROOT).as_posix()
            if relative in ignored or '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
                continue
            if relative not in files:
                if relative not in tracked:
                    raise ValueError(f'Unmanaged file in bundle; move it before refreshing: {relative}')
                removals.append(path)
    for relative, (content, mode) in files.items():
        path = ROOT / relative
        ensure_safe_destination(path)
        if (path.exists() and relative != 'bundles.json' and relative not in tracked
                and path.read_bytes() != content):
            raise ValueError(f'Unmanaged file would be overwritten; move it before refreshing: {relative}')
        if not path.exists() or path.read_bytes() != content or stat.S_IMODE(path.stat().st_mode) != mode:
            changes.append((path, content, mode))
    print(f'Bundle refresh: {len(changes)} changed files, {len(removals)} removed files')
    if check or dry_run:
        return not changes and not removals
    for path, content, mode in changes:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.bundle-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(content)
                os.fchmod(stream.fileno(), mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    for path in removals:
        path.unlink()
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--templates', required=True, type=Path, help='template_config Git checkout; committed HEAD is used')
    parser.add_argument('--chthm', required=True, type=Path, help='chthm_py Git checkout; committed HEAD is used')
    parser.add_argument('--gotham', type=Path, help='Gotham TOML source; defaults to the existing bundled palette')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Exit unsuccessfully if the snapshots need refreshing')
    mode.add_argument('--dry-run', action='store_true', help='Report changes without writing files')
    args = parser.parse_args(argv)
    try:
        template_commit, templates = snapshot(args.templates)
        chthm_commit, chthm = snapshot(args.chthm)
        templates['install.py'] = (template_installer(templates['install.py'][0]), 0o755)
        # Qt INI formatting only; avoid adding an empty trailing line on refresh.
        clementine = '.config/Clementine/Clementine.conf'
        content, permissions = templates[clementine]
        templates[clementine] = (content.rstrip(b'\n') + b'\n', permissions)
        session = ROOT / 'configs/.xinitrc'
        ensure_safe_destination(session)
        templates['.xinitrc'] = (session.read_bytes(), 0o755)
        gotham_path = args.gotham or ROOT / 'vendor/chthm/themes/gotham.toml'
        gotham = gotham_path.read_bytes()
        palette = tomllib.loads(gotham.decode())['colors']['primary']
        if palette.get('background') != '#0a0f14' or palette.get('foreground') != '#98d1ce':
            raise ValueError('Gotham palette must match the bundled default configuration')
        chthm['themes/gotham.toml'] = (gotham, 0o644)
        if 'themes/alacritty-theme.LICENSE' not in chthm:
            raise ValueError('Missing upstream theme license')
        files = {f'configs/{name}': value for name, value in templates.items()}
        files.update({f'vendor/chthm/{name}': value for name, value in chthm.items()})
        manifest = {
            'schema_version': 1,
            'template_config': {'commit': template_commit, 'destination': 'configs', 'sha256': digest(templates)},
            'chthm_py': {'commit': chthm_commit, 'destination': 'vendor/chthm', 'sha256': digest(chthm)},
            'local_adaptations': ['configs/.xinitrc', 'configs/install.py (.xinitrc support)',
                                 'configs/.config/Clementine/Clementine.conf (trailing blank line)',
                                 'vendor/chthm/themes/gotham.toml'],
            'files': sorted(files),
        }
        files['bundles.json'] = ((json.dumps(manifest, indent=2) + '\n').encode(), 0o644)
        matched = publish(files, check=args.check, dry_run=args.dry_run)
        return 0 if matched or not args.check else 1
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f'Bundle refresh failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
