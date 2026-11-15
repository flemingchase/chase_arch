# chase_arch

> [!NOTE]
> **Vibe-coding disclaimer:** this project was "vibe coded" with OpenAI Codex.
> Review and test the code and configuration before relying on it.

> [!WARNING]
> **Experimental:** this installer has not yet completed an end-to-end run in
> a disposable, freshly installed Arch Linux virtual machine. Review the
> package lists and configuration changes, run `./install.sh --dry-run` first,
> and keep a recoverable backup before using it on a real system.

Set up Chase's Qtile/X11 desktop on an already installed Arch Linux system,
then restore the bundled application configurations. The repository includes
the template files, so the target computer does not need another checkout.

This is a desktop bootstrapper. Start with a bootable Arch installation, a
normal user account, an internet connection, and either sudo access or a root
password for `su`.
Disk partitioning, bootloader setup, account creation and hardware-specific
graphics drivers belong to the base installation. The Bash entry script installs
`python` and `base-devel` before running the Python installer, so neither needs
to be installed beforehand. Both also remain in the main package manifest.

## Install

From your normal account on the installed system, install Git to download the
repository (or copy an extracted repository onto the machine):

```sh
su -c 'pacman -Syu --needed git'
# If your account already has sudo access, use sudo instead of su.
```

After publishing this repository on GitHub, clone its actual repository URL:

```sh
git clone https://github.com/YOUR_USERNAME/chase_arch.git
cd chase_arch
./install.sh --dry-run
./install.sh
```

Replace `YOUR_USERNAME` with the repository owner. No remote is configured in
this local starter repository yet. Do not run `sudo ./install.sh`: the installer
uses sudo for package installation and selected system changes when authorized,
and falls back to `su` otherwise. `su` requests the root password for each system
command; installing `base-devel` does not grant your account sudo access.
Pacman retains its normal interactive prompts, including package conflicts.
The default package transaction performs a full system upgrade.

The installer enables `ly@tty2.service` and disables `getty@tty2.service`
so Ly owns TTY 2 at the next boot. If an existing display manager is registered
through `display-manager.service`, its service is disabled first. Services are
not stopped or started during installation; reboot when ready, then select
Ly's **xinitrc** session to launch Qtile.

The installed `~/.xinitrc` is executable and contains only a shell shebang and
`exec qtile start -b x11`. It does not start applets or authentication agents.
Ly handles the X11 session setup; `xorg-xauth` remains installed for X11 support.
PipeWire and WirePlumber are included for audio; check their user services if
audio is unavailable on the new machine.

## Options

```sh
# Enable NetworkManager at the next boot; change the login shell to zsh.
./install.sh --enable-network --zsh

# Restore only settings, with per-file backups when contents change.
./install.sh --configs-only

# Preview settings in a separate staging home.
./install.sh --configs-only --home /tmp/chase-arch-preview --dry-run

# Install packages and configure Ly without copying user settings.
./install.sh --packages-only

# Also install the optional AUR list using an already installed helper.
./install.sh --aur-helper paru

# After starting Firefox once, close it and choose its actual profile directory.
./install.sh --configs-only --firefox-profile /path/to/your/firefox/profile
```

`--dry-run` works with every mode, performs no package installation or file writes,
and can run on another OS when Python is available. Without Python, a normal
`--dry-run` shows only the prerequisite installation and explains that the rest
of the preview is unavailable. Help and previews never install prerequisites.
`--configs-only` requires an existing Python installation and never installs
packages. `--home` is limited to configuration-only runs.
The Firefox profile must already exist; find it through `about:support`.

`--enable-network` enables NetworkManager for future boots without switching the
current connection. Use it when NetworkManager will manage the target machine;
resolve any competing network services before rebooting. Connect using `nmtui`
or the desktop applet. `--zsh` invokes `chsh`, which may request your password;
the new shell applies at your next login.

## Packages and templates

- `packages/official.txt`: core desktop, applications, fonts, audio and utilities.
- `packages/aur.txt`: optional Clementine, Sioyek Git version and neovim-remote.
- `configs/`: copied template bundle, including shell/Vim settings and plugin
  snapshots, Qtile wallpaper/widget, browser styles and the X11 session entry.
- `configs/install.py`: the original template restore helper, extended to copy
  `.xinitrc` as well. See `configs/README.rst` for application-specific notes.

Edit the package manifests and configurations to customize future installs.
Package lists accept one package name per line and `#` comments. AUR helper
installation is deliberately separate: install `paru` or `yay` following its
upstream instructions, review the packages, then pass `--aur-helper`. The default
install restores their configuration files but does not install AUR applications.
Hardware-specific driver selection and optional TeX, Python environment managers,
Dropbox and other specialist shell tools are left to the user.

Super+Return opens a terminal, Super+Space opens Rofi, Super+t opens the file
manager, and Super+a opens qutebrowser. Super+Ctrl+q exits Qtile. The templates
use large fonts; adjust them for your display if needed.

## Backups and repeat runs

Unchanged configuration files are skipped. Changed files are backed up beside
the destination as `FILENAME.template-backup-TIMESTAMP-ID`. Existing symlinks
are kept, and their targets receive the replacement and backup. Close affected
applications before restoring settings. To restore an individual file, close
its application and copy the chosen backup over that file (or its symlink target).
New files have no prior backup; remove them manually if reverting the setup.

Installation is not a transaction: if a later step fails, earlier completed
package or configuration changes remain. Correct the reported problem and rerun.
There is no automatic package removal or full-system rollback.

## Development and validation

```sh
python3 -m unittest discover -s tests -v
bash -n install.sh
sh -n configs/.xinitrc
```

Automated checks cover previews, configuration backups and repeated writes,
symlink preservation, package-list validation, executable session scripts,
Ly service setup, prerequisite bootstrapping without Python, sudo/su selection,
bootstrap failures and invalid Firefox profiles.
Package names were checked against the development machine's Arch repository
database. A complete fresh-Arch virtual-machine install and interactive desktop
check are still required before removing the experimental label.

The initial template snapshot came from `template_config` on 2026-11-10.
Your original template directory is unchanged.

## License

Original chase_arch code, documentation and configuration files are released
under the [Zero-Clause BSD license](LICENSE). Bundled Vim plugins and the
wallpaper retain their upstream terms; see
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

## References

- [Arch system maintenance and full upgrades](https://wiki.archlinux.org/title/System_maintenance)
- [Qtile on Arch](https://wiki.archlinux.org/title/Qtile)
- [Ly installation and service setup](https://wiki.archlinux.org/title/Ly)
- [Ly upstream documentation](https://github.com/fairyglade/ly#systemd)
- [Arch User Repository](https://wiki.archlinux.org/title/Arch_User_Repository)
