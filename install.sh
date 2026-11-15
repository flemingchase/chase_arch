#!/usr/bin/env bash
set -euo pipefail
script_directory=${BASH_SOURCE[0]%/*}
[[ $script_directory != "${BASH_SOURCE[0]}" ]] || script_directory=.
cd -- "$script_directory"

# Bootstrap in Bash: a base-only installation does not include Python or sudo.
preview=false
configs_only=false
help=false
arguments=("$@")
while (( $# )); do
    case "$1" in
        --dry-run) preview=true ;;
        --configs-only) configs_only=true ;;
        --help|-h) help=true ;;
        --home|--firefox-profile|--aur-helper)
            if (( $# < 2 )); then
                printf 'chase_arch: %s requires a value.\n' "$1" >&2
                exit 2
            fi
            shift ;;
        --home=*|--firefox-profile=*|--aur-helper=*|--packages-only|--no-aur|--enable-network|--zsh) ;;
        *) printf 'chase_arch: unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done
set -- "${arguments[@]}"

if $preview || $help || $configs_only; then
    if command -v python3 >/dev/null 2>&1; then
        exec python3 ./install.py "$@"
    fi
    if $help; then
        printf '%s\n' 'Usage: ./install.sh [--dry-run] [--configs-only | --packages-only]' \
            '  [--home PATH] [--firefox-profile PATH] [--aur-helper yay|paru]' \
            '  [--no-aur] [--enable-network] [--zsh]' \
            'A normal install bootstraps python and base-devel, then installs yay by default.'
        exit 0
    fi
    if $preview && ! $configs_only; then
        printf '%s\n' 'Would install prerequisites as root: pacman -Syu --needed -- python base-devel' \
            'Python is not installed, so the remaining desktop/configuration preview is unavailable.' \
            'Preview complete; nothing changed.'
        exit 0
    fi
    printf '%s\n' 'chase_arch: configuration-only mode requires Python. Run a normal install first.' >&2
    exit 1
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

if ! pacman -Q python base-devel >/dev/null 2>&1; then
    if [[ $CHASE_ARCH_PRIVILEGE == sudo ]]; then
        sudo pacman -Syu --needed -- python base-devel
    else
        su -c 'pacman -Syu --needed -- python base-devel'
    fi
fi
exec python3 ./install.py "$@"
