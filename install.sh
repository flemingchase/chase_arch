#!/usr/bin/env bash
set -euo pipefail
script_directory=${BASH_SOURCE[0]%/*}
[[ $script_directory != "${BASH_SOURCE[0]}" ]] || script_directory=.
cd -- "$script_directory"

# Bootstrap in Bash: a base-only installation does not include Python or sudo.
preview=false
configs_only=false
packages_only=false
help=false
list_apps=false
has_home=false
has_profile=false
aur_helper=
no_aur=false
enable_network=false
change_shell=false
keep_shell=false
offline_themes=false
has_template_repo=false
arguments=("$@")

argument_error() {
    printf 'chase_arch: %s\n' "$1" >&2
    exit 2
}

# Validate the command line before bootstrapping Python or requesting root
# access. Python repeats these checks for direct install.py invocations.
while (( $# )); do
    case "$1" in
        --dry-run) preview=true ;;
        --configs-only) configs_only=true ;;
        --packages-only) packages_only=true ;;
        --help|-h) help=true ;;
        --list-apps) list_apps=true ;;
        --no-aur) no_aur=true ;;
        --enable-network) enable_network=true ;;
        --zsh) change_shell=true ;;
        --keep-shell) keep_shell=true ;;
        --offline-themes) offline_themes=true ;;
        --home|--firefox-profile|--librewolf-profile|--aur-helper|--template-repo|--with|--home=*|--firefox-profile=*|--librewolf-profile=*|--aur-helper=*|--template-repo=*|--with=*)
            option=${1%%=*}
            if [[ $1 == *=* ]]; then
                value=${1#*=}
            else
                if (( $# < 2 )) || [[ -z $2 || $2 == -* ]]; then
                    argument_error "$option requires a value."
                fi
                shift
                value=$1
            fi
            [[ -n $value ]] || argument_error "$option requires a value."
            case "$option" in
                --home) has_home=true ;;
                --template-repo) has_template_repo=true ;;
                --with)
                    application_list_pattern='^[[:space:]]*[a-z0-9][a-z0-9_-]*[[:space:]]*(,[[:space:]]*[a-z0-9][a-z0-9_-]*[[:space:]]*)*$'
                    [[ $value =~ $application_list_pattern ]] || argument_error '--with requires comma-separated application names without empty entries.' ;;
                --firefox-profile|--librewolf-profile) has_profile=true ;;
                --aur-helper)
                    [[ $value == yay || $value == paru ]] || argument_error '--aur-helper must be yay or paru.'
                    aur_helper=$value ;;
            esac ;;
        *) argument_error "unknown argument: $1" ;;
    esac
    shift
done
set -- "${arguments[@]}"

if $configs_only && $packages_only; then
    argument_error '--configs-only cannot be combined with --packages-only.'
fi
if [[ -n $aur_helper ]] && $no_aur; then
    argument_error '--aur-helper cannot be combined with --no-aur.'
fi
if $change_shell && $keep_shell; then
    argument_error '--zsh cannot be combined with --keep-shell.'
fi
if $has_home && ! $configs_only; then
    argument_error '--home requires --configs-only.'
fi
if $configs_only && { [[ -n $aur_helper ]] || $no_aur || $enable_network || $change_shell || $keep_shell; }; then
    argument_error '--configs-only cannot be combined with system setup options.'
fi
if $packages_only && { $has_profile || $offline_themes || $has_template_repo; }; then
    argument_error 'Browser profile, template and theme options cannot be combined with --packages-only.'
fi

if $preview || $help || $list_apps || $configs_only; then
    if command -v python3 >/dev/null 2>&1; then
        exec python3 ./install.py "$@"
    fi
    if $help; then
        printf '%s\n' 'Usage: ./install.sh [--dry-run] [--configs-only | --packages-only]' \
            '  [--with APP[,APP...]] [--list-apps]' \
            '  [--home PATH] [--template-repo URL_OR_PATH] [--firefox-profile PATH] [--librewolf-profile PATH]' \
            '  [--aur-helper yay|paru | --no-aur] [--offline-themes] [--enable-network] [--keep-shell | --zsh]' \
            'Core applications: zsh, Vim, Qtile, Ly, Alacritty, qutebrowser, Rofi and chthm.' \
            'Normal installs select zsh as the login shell; use --keep-shell to retain the current shell.'
        exit 0
    fi
    if $list_apps; then
        printf '%s\n' 'chase_arch: --list-apps requires Python to read packages/apps.toml. No changes were made.' >&2
        exit 1
    fi
    if $preview && ! $configs_only; then
        printf '%s\n' 'Would install prerequisites as root: pacman -Syu --needed -- python git' \
            'Python is not installed, so the remaining desktop/configuration preview is unavailable.' \
            'Preview complete; nothing changed.'
        exit 0
    fi
    printf '%s\n' 'chase_arch: configuration-only mode requires Python. Run a normal install first.' >&2
    exit 1
fi

# Resolve application names and option combinations before requesting root
# access when Python is already available. Without Python, only the syntax
# checks above can run before installing the two bootstrap prerequisites.
if command -v python3 >/dev/null 2>&1; then
    python3 ./install.py --validate-options "$@"
fi

if (( EUID == 0 )); then
    printf '%s\n' 'chase_arch: run as your normal desktop user, without sudo.' >&2
    exit 1
fi
if [[ ! -r /etc/os-release ]]; then
    printf '%s\n' 'chase_arch: package installation requires Arch Linux.' >&2
    exit 1
fi
. /etc/os-release
if [[ ${ID:-} != arch || -d /run/archiso ]]; then
    printf '%s\n' 'chase_arch: boot your installed Arch Linux system first.' >&2
    exit 1
fi

if command -v sudo >/dev/null 2>&1 && sudo -v; then
    export CHASE_ARCH_PRIVILEGE=sudo
elif command -v su >/dev/null 2>&1; then
    printf '%s\n' 'Using su for system changes; enter the root password when prompted.'
    export CHASE_ARCH_PRIVILEGE=su
else
    printf '%s\n' 'chase_arch: sudo access or su with a root password is required.' >&2
    exit 1
fi

if ! pacman -Q python git >/dev/null 2>&1; then
    if [[ $CHASE_ARCH_PRIVILEGE == sudo ]]; then
        sudo pacman -Syu --needed -- python git
    else
        su -c 'pacman -Syu --needed -- python git'
    fi
fi
exec python3 ./install.py "$@"
