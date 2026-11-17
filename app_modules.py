"""Resolve the required desktop and opt-in application modules from manifests."""

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parent
CORE_APPS = ('zsh', 'vim', 'qtile', 'ly', 'alacritty', 'qutebrowser', 'rofi', 'chthm')
# chthm is installed from the bundled source rather than a pacman package.
CORE_PACKAGES = tuple(name for name in CORE_APPS if name != 'chthm')
CORE_SUPPORT_APPS = ('qt6ct',)
CORE_COMPONENTS = ('zsh', 'vim', 'qtile', 'alacritty', 'qutebrowser', 'rofi', 'qt6ct')
CORE_TARGETS = ('alacritty', 'qtile', 'qutebrowser', 'rofi', 'qt6ct')
PACKAGE_NAME = re.compile(r'[a-z0-9][a-z0-9@._+\-]*')


def packages(filename):
    result = []
    for line in filename.read_text().splitlines():
        name = line.partition('#')[0].strip()
        if not name:
            continue
        if not PACKAGE_NAME.fullmatch(name):
            raise ValueError(f'Invalid package name in {filename}: {name!r}')
        if name not in result:
            result.append(name)
    if not result:
        raise ValueError(f'Empty package list: {filename}')
    return result


def load_catalog(root=ROOT):
    document = tomllib.loads((root / 'packages/apps.toml').read_text())
    if document.get('schema_version') != 1 or not isinstance(document.get('apps'), dict):
        raise ValueError('Invalid application catalog')
    catalog = document['apps']
    for name, module in catalog.items():
        if (not re.fullmatch(r'[a-z][a-z0-9-]*', name) or name in CORE_APPS + CORE_SUPPORT_APPS
                or not isinstance(module, dict) or not isinstance(module.get('description'), str)):
            raise ValueError(f'Invalid application module: {name}')
        unknown = set(module) - {'description', 'official', 'aur', 'requires', 'components', 'targets'}
        if unknown:
            raise ValueError(f'Unknown module fields for {name}: {", ".join(sorted(unknown))}')
        for key in ('official', 'aur', 'requires', 'components', 'targets'):
            values = module.get(key, [])
            if (not isinstance(values, list) or any(not isinstance(value, str)
                    or not PACKAGE_NAME.fullmatch(value) for value in values)):
                raise ValueError(f'Invalid {key} list for {name}')
        for required in module.get('requires', []):
            if required not in catalog and required not in CORE_APPS + CORE_SUPPORT_APPS:
                raise ValueError(f'Unknown dependency {required} for {name}')
    return catalog


@dataclass(frozen=True)
class Selection:
    optional: tuple[str, ...]
    official: tuple[str, ...]
    aur: tuple[str, ...]
    components: tuple[str, ...]
    targets: tuple[str, ...]


def resolve_selection(groups=(), *, root=ROOT, no_aur=False, aur_helper='yay'):
    catalog = load_catalog(root)
    requested = []
    for group in groups:
        names = [name.strip() for name in group.split(',')]
        if any(not name for name in names):
            raise ValueError('--with requires nonempty comma-separated application names')
        requested.extend('librewolf' if name == 'librefox' else name for name in names)
    unknown = set(requested) - set(catalog) - set(CORE_APPS + CORE_SUPPORT_APPS)
    if unknown:
        raise ValueError('Unknown optional applications: ' + ', '.join(sorted(unknown)) + '; use --list-apps')
    selected, visiting = [], set()
    def include(name):
        if name in CORE_APPS + CORE_SUPPORT_APPS or name in selected:
            return
        if name in visiting:
            raise ValueError(f'Application dependency cycle involving {name}')
        visiting.add(name)
        for required in catalog[name].get('requires', []):
            include(required)
        visiting.remove(name)
        selected.append(name)
    for name in requested:
        include(name)
    official = packages(root / 'packages/core.txt') + packages(root / 'packages/support.txt')
    if not set(CORE_PACKAGES + CORE_SUPPORT_APPS) <= set(official):
        raise ValueError('The manifests must include all required application and theme-support packages')
    aur, components, targets = [], list(CORE_COMPONENTS), list(CORE_TARGETS)
    for name in selected:
        module = catalog[name]
        official.extend(module.get('official', []))
        aur.extend(module.get('aur', []))
        components.extend(module.get('components', []))
        targets.extend(module.get('targets', []))
    if no_aur and aur:
        raise ValueError('--no-aur conflicts with selected AUR applications: ' + ', '.join(aur))
    if aur:
        official.append('base-devel')
        if aur_helper == 'yay':
            official.append('go')
    unique = lambda values: tuple(dict.fromkeys(values))
    return Selection(tuple(selected), unique(official), unique(aur), unique(components), unique(targets))


def print_catalog():
    print('Required: ' + ', '.join(CORE_APPS))
    print('Optional applications and features (select with --with NAME[,NAME...]):')
    for name, module in load_catalog().items():
        dependencies = module.get('requires', [])
        note = ' [AUR]' if module.get('aur') else ''
        if dependencies:
            note += ' [includes ' + ', '.join(dependencies) + ']'
        print(f'  {name:20} {module["description"]}{note}')
