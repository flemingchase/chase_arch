# chase_arch

> [!NOTE]
> This project was developed with OpenAI Codex. Review its configuration and
> package choices before installing them.

> [!WARNING]
> Experimental: automated checks and isolated configuration/browser installs
> have passed, but a complete installation in a fresh Arch virtual machine has
> not yet been performed. Package installation changes the target system.

One repository sets up a Qtile/X11 desktop on a fresh, already bootable Arch
Linux installation. The normal installer performs these steps in order:

1. Install the official packages and AUR applications.
2. Initialize Firefox and LibreWolf's native default profiles when necessary.
3. Restore the bundled Gotham application configurations and browser layouts.
4. Install the bundled chthm program, connect it to those configurations, and
   select Gotham without restarting applications.
5. Enable Ly for the next boot, with optional NetworkManager and login-shell setup.

Both `template_config` and `chthm_py` are included as source snapshots in this
repository. There are no Git submodules and no sibling checkouts to download.
The installed chthm program has its own private copy under the destination
user's home; it continues to work after the downloaded installer is removed.

## Start from a base Arch installation

Boot the installed system, log in as a normal user, and establish an internet
connection. You need either sudo access or the root password for `su`. Disk
partitioning, bootloader setup, user creation and hardware-specific graphics
selection remain part of the base installation.

Install Git if it is missing, then download this one repository:

```sh
su -c 'pacman -Syu --needed git'
# Or: sudo pacman -Syu --needed git

git clone --depth 1 https://github.com/flemingchase/chase_arch.git
cd chase_arch
./install.sh --dry-run
./install.sh
```

An extracted GitHub ZIP also works: enter its directory and run `bash install.sh`.
Run the installer as the normal desktop user, without `sudo` in front of it.
The Bash entry point installs Python and base-devel if they are missing, then
runs the Python coordinator. Package transactions use sudo when authorized,
or interactive root-password prompts through su. No sudo privileges are granted
implicitly. Pacman and the AUR helper retain their normal review prompts.

The standard run installs yay if necessary, building it as the normal user,
and installs Clementine, Sioyek and neovim-remote through it. Its privileged
package commands also support the su path. Official packages include Firefox,
LibreWolf, qutebrowser, Qtile, Alacritty, Rofi, Zathura, PCManFM-Qt, qt6ct,
zsh, Vim, Neovim, fonts, audio and desktop utilities. Official package installation
uses a full `pacman -Syu` transaction rather than a partial upgrade.

The default palette is Gotham: background `#0a0f14`, foreground `#98d1ce`.
Firefox and LibreWolf have square compact tabs and the bundled layouts;
qutebrowser uses the current tab/status-bar layout and 125% page zoom. Website
colors remain under website control, with a native dark preference and no
forced website stylesheets.

Close affected applications before rerunning the installer. Existing browser
profiles are reused; if selection is ambiguous, specify their paths explicitly.
A fresh browser is initialized briefly in headless mode on a blank page so its
own installation-specific default profile receives the overlay. Existing locked
profiles are rejected rather than overwritten while the browser is running.
No browsing history, accounts, credentials or extensions are imported.

## First login and theme changes

After installation, reboot and select the **xinitrc** session in Ly. The installer
enables `ly@tty2.service`, disables `getty@tty2.service`, and disables another
registered display manager if present. It does not stop the current session or
start/restart services during installation.

The bundled `.xinitrc` adds `~/.local/bin` to PATH and launches Qtile. This makes
chthm available in desktop terminals even if your login shell remains Bash.
The zsh configuration additionally loads chthm's shell integration. To make zsh
your login shell during installation, use `./install.sh --zsh`.

```sh
chthm list
chthm gotham
chthm kimbie_dark
```

The installer seeds Gotham and Kimbie Dark locally, then chthm attempts to
retrieve its larger upstream theme catalogue. If that download fails, the
bundled themes remain usable. Use `--offline-themes` to skip this catalogue
download deliberately; this does not make package installation offline.

Qt 6 applications share qt6ct's palette. Firefox and LibreWolf apply changed
browser-interface styles after restart. Normal chthm theme changes retain the
program's application-reload behavior; the installer uses `--no-reload` for its
initial theme selection.

Super+Return opens a terminal, Super+Space opens Rofi, Super+t opens the file
manager, and Super+a opens qutebrowser. Super+Ctrl+q exits Qtile.

## Options

```sh
# Optional: use NetworkManager on future boots and choose zsh as login shell.
./install.sh --enable-network --zsh

# Restore the configurations, then install/reconnect chthm and select Gotham.
# Uses installed programs; does not install packages or change services.
./install.sh --configs-only

# Stage only user files in another home, using the bundled theme collection.
./install.sh --configs-only --home /tmp/chase-arch-preview --offline-themes

# Inspect that same operation without writes or browser initialization.
./install.sh --configs-only --home /tmp/chase-arch-preview --offline-themes --dry-run

# Install packages and configure Ly, without user configurations or chthm.
./install.sh --packages-only

# Use an already installed paru instead of bootstrapping yay.
./install.sh --aur-helper paru

# Skip AUR applications; all three browsers are in the official package list.
./install.sh --no-aur

# Choose existing profiles when automatic discovery is ambiguous.
./install.sh --configs-only \
  --firefox-profile /path/to/firefox/profile \
  --librewolf-profile /path/to/librewolf/profile
```

`--dry-run` performs no installs, writes, theme downloads or browser starts.
With Python available it previews the complete workflow and validates existing
profile/template destinations. Without Python it shows the prerequisite phase
and explains why the remaining preview is unavailable. Help and preview never
bootstrap Python. Invalid option combinations are rejected in Bash first.

`--configs-only` requires Python and the applications you want configured to
already be installed; installing zsh also enables chthm's shell syntax check. `--home` is
limited to this mode and isolates HOME, XDG configuration/data/state/cache paths
and ZDOTDIR. It does not install system packages into that directory. An explicit
browser profile must already exist; use `about:support` to find it.

`--enable-network` enables NetworkManager without switching the current
connection. Select it when NetworkManager should own the new system's network
configuration; avoid conflicting network managers. `--zsh` invokes `chsh`, which
may request your password and takes effect on the next login.

## Included files and scope

- `install.sh`: base-Arch bootstrap and argument validation.
- `install.py`: package → profiles → templates → chthm orchestration.
- `browser_profiles.py`: native Firefox/LibreWolf profile discovery and setup.
- `packages/official.txt` and `packages/aur.txt`: editable package manifests.
- `configs/`: current template snapshot, including its original licenses.
- `vendor/chthm/`: bundled chthm installer, source, tests, themes and licenses.
- `bundles.json`: source commit IDs, content hashes and bundled-file inventory.
- `tools/sync_bundles.py`: maintainer refresh command.
- `tools/su_exec.py`: argument-preserving adapter for AUR privilege commands.

The configuration snapshot includes `.xinitrc` support specific to this central
installer. The source template and chthm repositories remain independently
usable. Editing or pushing either source repository does not automatically
update this bundle: refresh the snapshots and commit the resulting changes here.

Ly's system configuration and the Plymouth artwork shipped inside `configs/`
remain available for manual restoration as described in `configs/README.rst`.
The central installer enables Ly but does not configure a boot splash, rebuild
initramfs images, change bootloader options, or choose GPU-specific drivers.
TeX toolchains and specialist shell tools are also outside the default setup.

## Backups and repeat runs

Template restoration skips identical files and creates unique
`FILENAME.template-backup-TIMESTAMP-ID` backups before replacing changed files.
Existing dotfile symlinks are preserved. chthm then adds its managed integration
blocks and maintains its own backups. Rerunning the full/configuration workflow
reapplies the bundled defaults and selects Gotham; use `chthm THEME` for an
ordinary theme change that does not restore the templates.

New files have no previous version to back up. Restore a template backup while
its application is closed. Installation is not a transaction: if a later step
fails, earlier package/configuration changes remain. Correct the reported
problem and rerun; there is no automatic package removal or system rollback.

## Updating the bundled projects

Commit desired source changes first. From this central repository:

```sh
python3 tools/sync_bundles.py \
  --templates /path/to/template_config \
  --chthm /path/to/chthm_py \
  --dry-run

python3 tools/sync_bundles.py \
  --templates /path/to/template_config \
  --chthm /path/to/chthm_py
```

The refresh reads committed tracked files, excludes Git metadata and caches,
preserves the central `.xinitrc` adapter, retains license notices, and records
source revisions in `bundles.json`. `--check` verifies synchronization without
writing. An optional `--gotham PATH` replaces the bundled Gotham source when
refreshing. No source checkouts are needed by people installing the published
central repository.

## Development and validation

```sh
python3 -m unittest discover -s tests -v
bash -n install.sh
sh -n configs/.xinitrc

(cd configs && python3 -m unittest discover -s tests -v)
(cd vendor/chthm && PYTHONPATH=src python3 -m unittest discover -s tests -v)
```

Tests cover prerequisite bootstrapping without Python, sudo/su selection,
argument rejection before side effects, ordered setup, dry runs, isolated target
homes, native profile discovery/locks, backups, executable session files,
repeat runs and theme installation. The bundled projects retain their own tests.
Real browser initialization and the configuration/chthm sequence can be checked
in a disposable home with `--configs-only --home ... --offline-themes`.
A full fresh-Arch VM installation is still required to validate package builds,
login-manager startup, hardware and the interactive desktop together.

## License and references

Original chase_arch material uses the [Zero-Clause BSD license](LICENSE).
Bundled projects, themes, plugins and artwork retain their upstream terms;
see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

- [Arch system maintenance and full upgrades](https://wiki.archlinux.org/title/System_maintenance)
- [Arch User Repository](https://wiki.archlinux.org/title/Arch_User_Repository)
- [LibreWolf installation on Arch](https://librewolf.net/installation/arch/)
- [qt6ct in Arch Extra](https://archlinux.org/packages/extra/x86_64/qt6ct/)
- [Ly service setup](https://github.com/fairyglade/ly#systemd)
