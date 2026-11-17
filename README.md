# chase_arch

> [!NOTE]
> This project was developed with OpenAI Codex. Review its configuration and
> package choices before installing them.

> [!WARNING]
> Experimental: automated checks and isolated installations are available, but
> a complete installation in a fresh Arch virtual machine is still required to
> validate package builds, login-manager startup and the graphical session.

A modular Qtile/X11 desktop installer for an already bootable Arch Linux system.
The default full installation includes these eight components:

| Role | Package |
| --- | --- |
| Shell | `zsh` |
| Text editor | `vim` |
| Window manager | `qtile` |
| Display manager | `ly` |
| Terminal emulator | `alacritty` |
| Web browser | `qutebrowser` |
| Application launcher | `rofi` |
| Theme switcher | `chthm` (bundled program) |

The core also installs the supporting packages listed in `packages/support.txt`:
Python, Git, Xorg, Xauth, Mesa, Fira Mono and qt6ct for shared Qt 6 theme support.
The seven official application packages are listed in `packages/core.txt`;
chthm is installed from `vendor/chthm/`, not through pacman. Pacman resolves
package dependencies.
Other applications and features are opt-in; the default run does not install an
AUR helper or build toolchain.

Application configurations come from
[template_config](https://github.com/flemingchase/template_config). Each full or
configuration-only run shallow-clones its current default branch into a temporary
directory, reports the commit, and restores only the selected components. The
checkout is removed after success or failure. No template snapshot or Git
submodule is carried in this repository.

## Install the core

Boot the installed Arch system, log in as a normal user, and establish an internet
connection. Disk partitioning, bootloader setup, user creation and hardware-specific
graphics configuration are outside this installer. Sudo access or the root password
for `su` is required for system changes.

```sh
# Install Git if necessary, using either su or sudo.
su -c 'pacman -Syu --needed git'

git clone --depth 1 https://github.com/flemingchase/chase_arch.git
cd chase_arch
./install.sh --dry-run
./install.sh
```

Run as the normal desktop user, without `sudo` before `install.sh`. An extracted
GitHub ZIP also works with `bash install.sh`. The entry script installs Python and
Git when necessary; the coordinator installs the selected official packages with
a full `pacman -Syu --needed` transaction. Existing sudo/su authorization and normal
package-review prompts are preserved.

The installer validates the retrieved template restore plan before the main package
transaction, installs selected packages, prepares selected browser profiles, restores
selected configurations, installs its own `session/xinitrc` launcher, and installs
or reconnects chthm with Gotham selected. It then
enables Ly for the next boot and makes zsh the login shell. Use `--keep-shell` to
retain your existing login shell while still installing zsh and `.zshrc`. `--zsh`
remains accepted as a compatibility alias for the default shell behavior.

After installation, reboot and select the **xinitrc** session in Ly. The installer
enables `ly@tty2.service`, disables `getty@tty2.service`, and disables another
registered display manager if present. It does not start or restart services or
stop the current graphical session. The login-shell change may prompt for your
password and takes effect on the next login.

## Choose optional applications

```sh
./install.sh --list-apps

# Add a PDF viewer, file manager and audio.
./install.sh --with zathura,pcmanfm-qt,audio

# The option can be repeated.
./install.sh --with firefox --with librewolf

# AUR applications use yay by default, installed only when needed.
./install.sh --with clementine,sioyek

# Use an already installed paru for selected AUR applications.
./install.sh --with neovim-remote --aur-helper paru
```

`--with` accepts comma-separated names from `packages/apps.toml`. Dependencies
between modules are included automatically. Core components cannot be removed
through this option; naming an already included core component is accepted and
does not add another installation. `librefox` is accepted as an alias for `librewolf`.

| Option name | Adds | Additional modules |
| --- | --- | --- |
| `zathura` | Zathura and its MuPDF PDF backend | — |
| `clementine` | Clementine from the AUR | — |
| `sioyek` | `sioyek-git` from the AUR | — |
| `plymouth` | Plymouth package; boot setup remains manual | — |
| `firefox` | Firefox and its profile overlay | — |
| `librewolf` | LibreWolf and its profile overlay | — |
| `pcmanfm-qt` | File manager and Adwaita icons | — |
| `neovim` | Additional text editor | — |
| `neovim-remote` | AUR remote command for Neovim | `neovim` |
| `audio` | PipeWire, ALSA/PulseAudio compatibility and WirePlumber | — |
| `networkmanager` | NetworkManager package | — |
| `network-manager-applet` | NetworkManager tray applet | `networkmanager` |
| `polkit` | Polkit and the LXQt authorization agent | — |
| `file-roller` | Archive manager | — |
| `lxqt-sudo` | Graphical privilege prompt | — |
| `fzf` | Fuzzy selector used by shell functions | — |
| `scrot` | Screenshot command | — |
| `xsel` | X11 clipboard command | — |
| `xrandr` | X11 display configuration command | — |
| `xset` | X11 command used by the Caps Lock indicator | — |

Clementine, Sioyek and PCManFM-Qt use the qt6ct support already included in the core.

`base-devel` is added only for selected AUR packages; building yay additionally
requires Go. `--no-aur` rejects a selection containing AUR applications rather
than silently omitting them. AUR packages are built as the normal user.

`--with networkmanager` installs the package without enabling its service.
`--enable-network` both selects NetworkManager and enables it for future boots,
without switching the current connection. Use this only when NetworkManager should
manage the destination system's network configuration.

Rerunning with a smaller selection does not uninstall previously installed optional
applications or delete their existing settings. Select the modules you want to
install or restore on each run.

## Configurations, browsers and themes

The core restores the zsh, Vim, Qtile, Alacritty, qutebrowser, Rofi and qt6ct
components, then connects them to chthm and applies Gotham. Optional configuration
directories and browser overlays are restored only when their modules are selected. Firefox and LibreWolf
are not selected merely because their executables or profiles already exist.

For a selected Firefox or LibreWolf, the installer reuses its native default
profile or initializes one briefly in headless mode. Ambiguous selections require
an explicit existing profile directory; selecting a profile also selects its
browser module:

```sh
./install.sh --with firefox --firefox-profile /path/to/firefox/profile
./install.sh --configs-only --librewolf-profile /path/to/librewolf/profile
```

Close selected applications before restoration. Locked browser profiles are rejected.
No browsing history, accounts, credentials or extensions are imported. An explicit
profile path must already exist; find it on `about:support`.

Every full or configuration-only run installs or reconnects `chthm` from the
source retained in `vendor/chthm/`. The theme catalogue download can be skipped:

```sh
./install.sh --offline-themes

# After installation:
chthm list
chthm gotham
chthm kimbie_dark
```

Installation creates the private program copy and initially applies Gotham
without reloading applications. The initial command receives the selected theme
targets. Existing chthm settings still apply, including `additional_targets`;
its Qt migration can also remove its own older PCManFM-Qt stylesheet overrides.
Template component selection does not replace chthm's independent configuration.
Gotham and Kimbie Dark are seeded locally. Normally chthm also downloads its larger
theme catalogue; `--offline-themes` skips that catalogue download.
It does not make package installation or Git retrieval offline.
Ordinary later theme changes retain chthm's own reload behavior.

The Qtile template provides Super+Return for the terminal, Super+a for
qutebrowser, and Super+Space for Rofi, all available in the default setup.
Super+t requires the optional `pcmanfm-qt`, and the clipboard-clearing binding
requires `xsel`. The Caps Lock indicator remains empty
without `xset`. Shell functions using fzf or scrot require the corresponding optional
commands. These shortcuts/functions do not install their dependencies.

Open Vim as the destination user and run `:PlugInstall` to download VimTeX,
vim-airline, vim-airline-themes and UltiSnips. Git and internet access are needed;
downloaded plugin files are not distributed with the current templates. If upgrading
from an old plugin snapshot, review local edits and move the old `~/.vim/plugged`
directory to a backup before installing fresh plugin checkouts. Arch's `vim`
supports Python but lacks the X clipboard features supplied by `gvim`; `gvim` is
an alternative Vim package, not an additional core application. VimTeX compilation
and viewing require a TeX toolchain, latexmk and the selected viewer separately.

Ly's system configuration and Plymouth artwork remain in `template_config` for
manual restoration. `--with plymouth` installs its package only: it does not modify
bootloader arguments, add initramfs hooks or rebuild the initramfs. See the template
repository's `README.rst` for the system-file instructions.

## Installation modes

```sh
# Restore selected user configurations and chthm; no system package, service or shell changes.
./install.sh --configs-only --with zathura

# Stage selected user files in an isolated home.
./install.sh --configs-only --home /tmp/chase-arch-preview --offline-themes

# Preview without writes, retrieval or browser initialization.
./install.sh --configs-only --home /tmp/chase-arch-preview --dry-run

# Clone templates from another Git URL or a local Git repository.
./install.sh --configs-only --template-repo /path/to/template_config

# Install selected packages and configure Ly/zsh; skip user-file restoration and chthm.
./install.sh --packages-only --with audio
```

`--configs-only` requires Python, Git and the selected applications to be installed
already. It always installs or reconnects chthm. `--packages-only` skips all
user-level configuration and chthm installation steps. `--home` is limited
to `--configs-only` and isolates HOME, XDG directories and ZDOTDIR; it does not install
system packages into the staging directory.

`--dry-run` performs no installs, writes, Git clones, theme downloads or browser
starts. With Python available it previews the selection and validates profile
selection. Destination validation requires the retrieved template and occurs
during a real run before the main package transaction. Without Python, the preview
describes prerequisites and explains why the full plan is unavailable. Help and
listing/preview operations do not install prerequisites.

## Maintain the modules and source repositories

| File | Responsibility |
| --- | --- |
| `packages/core.txt` | The seven official core application packages; bundled chthm is separate |
| `packages/support.txt` | Supporting runtime, X11, graphics, fonts and qt6ct packages |
| `packages/apps.toml` | Optional modules: packages, dependencies, template components and theme targets |
| `app_modules.py` | Selection validation and dependency resolution |
| `install.sh` | Prerequisite bootstrap and command-line validation |
| `install.py` | Retrieval, installation and configuration orchestration |
| `browser_profiles.py` | Selected Firefox/LibreWolf profile handling |
| `session/xinitrc` | The Qtile/X11 session launcher |
| `vendor/chthm/` | Required theme-switcher source and its tests/licenses |
| `bundles.json`, `tools/sync_bundles.py` | chthm snapshot inventory and refresh |

Add an optional module to `packages/apps.toml` with its package lists and any
`requires`, `components` or `targets` entries. Package dependencies are handled by
pacman/AUR tooling; module dependencies express the additional selections needed
for this desktop configuration. A new template component must also be implemented
in the source template installer, and a new theme target requires a chthm adapter.

The retrieved template installer must support `--components`. Commit and push that
API and the intended configuration changes in `template_config` before installing
from GitHub. An older template installer is rejected during preflight rather than
being allowed to restore every component. Git retrieval uses committed files even
when `--template-repo` points to a local checkout; uncommitted edits are not included.
Subsequent template updates require committing and pushing the source repository,
with no snapshot synchronization in `chase_arch`.

To refresh the bundled chthm source, commit its desired source changes
and run:

```sh
python3 tools/sync_bundles.py --chthm /path/to/chthm_py --dry-run
python3 tools/sync_bundles.py --chthm /path/to/chthm_py
```

`--check` verifies that snapshot without writing. The refresh retains theme licenses,
excludes Git metadata/caches, and records the source commit in `bundles.json`.

## Backups and validation

Template restoration skips identical files, preserves existing dotfile symlinks,
and backs up changed files with `.template-backup-*` names. The session launcher
uses `.chase-arch-backup-*`; chthm maintains its own backups. Every full or
configuration-only reinstallation reapplies the selected defaults and reconnects
chthm afterward. Installation is not transactional: completed package/file
changes remain if a later step fails.

```sh
python3 -m unittest discover -s tests -v
bash -n install.sh
sh -n session/xinitrc
(cd vendor/chthm && PYTHONPATH=src python3 -m unittest discover -s tests -v)
```

Tests cover module selection, prerequisite handling, sudo/su behavior, isolated
homes, selected browser profiles, template retrieval and component arguments,
failure handling, backups and default theme integration. Repository tests use
local Git fixtures and do not install system packages. Component ownership and
selective-restoration tests live in `template_config` itself. A fresh Arch VM is
still needed to validate the complete installed desktop.

Original chase_arch material uses the [Zero-Clause BSD license](LICENSE).
Bundled chthm and themes retain their upstream terms; see
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

References: [Arch system maintenance](https://wiki.archlinux.org/title/System_maintenance),
[AUR](https://wiki.archlinux.org/title/Arch_User_Repository),
[Vim package variants](https://wiki.archlinux.org/title/Vim), and
[Ly service setup](https://wiki.archlinux.org/title/Ly).
