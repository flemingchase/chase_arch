"""Plan native Firefox/LibreWolf profiles and initialize first-run defaults."""

import configparser
from dataclasses import dataclass
import errno
import fcntl
import ipaddress
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile


APPLICATIONS = {"firefox": "Firefox", "librewolf": "LibreWolf"}


@dataclass(frozen=True)
class ProfilePlan:
    application: str
    home: Path
    config: Path
    root: Path
    path: Path | None
    create: bool


def profile_roots(application, home, config):
    """Native packages retain legacy profile locations when they already exist."""
    if application == "firefox":
        roots = (home / ".mozilla/firefox", config / "mozilla/firefox")
    elif application == "librewolf":
        roots = (home / ".librewolf", config / "librewolf/librewolf")
    else:
        raise ValueError(f"Unsupported browser: {application}")
    return tuple(dict.fromkeys(roots))


def _path(root, value, relative=True):
    path = Path(value)
    return (root / path if relative and not path.is_absolute() else path).resolve()


def discover_profile(application, roots):
    """Prefer install-specific defaults to the old ProfileN/Default marker."""
    label = APPLICATIONS[application]
    for root in roots:
        registry = root / "profiles.ini"
        if not registry.is_file():
            continue
        profiles = configparser.RawConfigParser()
        installs = configparser.RawConfigParser()
        try:
            profiles.read_string(registry.read_text())
            if (root / "installs.ini").is_file():
                installs.read_string((root / "installs.ini").read_text())
        except configparser.Error as error:
            raise ValueError(f"Cannot read {label} profile registry: {registry}: {error}") from error
        defaults = set()
        for section in profiles.sections():
            if section.startswith("Install") and profiles.has_option(section, "Default"):
                value = profiles.get(section, "Default")
                if value:
                    defaults.add(_path(root, value))
        for section in installs.sections():
            if installs.has_option(section, "Default"):
                value = installs.get(section, "Default")
                if value:
                    defaults.add(_path(root, value))
        candidates, legacy_defaults = set(), set()
        for section in profiles.sections():
            if section.startswith("Profile") and profiles.has_option(section, "Path"):
                path = _path(root, profiles.get(section, "Path"),
                             profiles.get(section, "IsRelative", fallback="1") == "1")
                candidates.add(path)
                if profiles.get(section, "Default", fallback="0") == "1":
                    legacy_defaults.add(path)
        candidates = defaults or legacy_defaults or candidates
        if len(candidates) > 1:
            raise ValueError(f"Multiple {label} profiles in {root}; select --{application}-profile PATH explicitly.")
        if candidates:
            selected = candidates.pop()
            if not selected.is_dir():
                raise ValueError(f"{label} default profile directory does not exist: {selected}")
            return root, selected
    return None


def plan_profiles(home, config, applications=("firefox", "librewolf"),
                  firefox_profile=None, librewolf_profile=None):
    """Inspect destinations without creating directories or starting browsers.

    A fresh plan has path=None: the browser chooses its profile name and
    registers the install-specific default during prepare_profiles().
    """
    home, config = Path(home).expanduser().absolute(), Path(config).expanduser().absolute()
    explicit = {"firefox": firefox_profile, "librewolf": librewolf_profile}
    plans = []
    for application in dict.fromkeys(applications):
        if application not in APPLICATIONS:
            raise ValueError(f"Unsupported browser: {application}")
        selected = explicit[application]
        if selected is not None:
            path = Path(selected).expanduser().resolve()
            if not path.is_dir():
                raise ValueError(f"{APPLICATIONS[application]} profile must already exist: {path}")
            plans.append(ProfilePlan(application, home, config, path.parent, path, False))
            continue
        roots = profile_roots(application, home, config)
        found = discover_profile(application, roots)
        if found:
            root, path = found
            plans.append(ProfilePlan(application, home, config, root, path, False))
        else:
            # Only a preview location: Gecko decides the native registry path.
            root = next((root for root in roots if root.is_dir()), roots[-1])
            plans.append(ProfilePlan(application, home, config, root, None, True))
    return plans


def _check_symlink_lock(path, have_fcntl_lock, label, profile):
    if not path.is_symlink():
        return
    try:
        target = os.readlink(path)
    except FileNotFoundError:
        return
    match = re.fullmatch(r"([^:]+):(\+?)([1-9][0-9]*)", target)
    if not match:
        raise ValueError(f"Cannot verify {label} is closed: unrecognized profile lock {path}")
    # Gecko treats +PID symlinks as stale when the fcntl lock can be taken.
    # The PID can have been recycled since the last browser session.
    if match[2] and have_fcntl_lock:
        return
    try:
        address = ipaddress.IPv4Address(match[1])
    except ipaddress.AddressValueError as error:
        raise ValueError(f"Cannot verify {label} is closed: invalid profile lock {path}") from error
    try:
        os.kill(int(match[3]), 0)
    except ProcessLookupError:
        if address.is_loopback:
            return
        # A PID absent locally does not prove a lock on another host is stale.
        raise ValueError(f"Cannot verify {label} is closed: profile lock {path} names a nonlocal address.")
    except PermissionError:
        pass  # A live process owned by another user is still a live process.
    raise ValueError(f"Close {label} before updating its in-use profile: {profile}")


def ensure_profiles_closed(plans):
    """Probe selected Linux profile locks without creating or changing files.

    Gecko leaves an unlocked .parentlock behind after a normal shutdown. Check
    its advisory lock rather than treating the file's presence as an open
    browser. O_RDWR is necessary for a POSIX write-lock probe; no data is
    written, and neither O_CREAT nor O_TRUNC is used.
    """
    for plan in plans:
        if plan.path is None:
            continue
        label = APPLICATIONS[plan.application]
        lock = plan.path / ".parentlock"
        descriptor = None
        have_fcntl_lock = False
        try:
            try:
                descriptor = os.open(lock, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
            except FileNotFoundError:
                pass
            if descriptor is not None:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ValueError(f"Cannot verify {label} is closed: invalid profile lock {lock}")
                try:
                    fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    if error.errno in (errno.EACCES, errno.EAGAIN):
                        raise ValueError(f"Close {label} before updating its in-use profile: {plan.path}") from error
                    raise
                have_fcntl_lock = True
            _check_symlink_lock(plan.path / "lock", have_fcntl_lock, label, plan.path)
        except OSError as error:
            raise ValueError(f"Cannot verify {label} is closed: {lock}: {error}") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)  # Releases only this process's probe locks.


def _initialize(command, environment):
    """Run only our headless first-run process; stop its group on timeout."""
    process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        output, error = process.communicate(timeout=60)
    except subprocess.TimeoutExpired as exception:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        raise ValueError(f"Timed out initializing {Path(command[0]).name}'s default profile.") from exception
    if process.returncode:
        detail = (error or output).strip()[-1000:]
        raise ValueError(f"{Path(command[0]).name} profile initialization failed "
                         f"(exit {process.returncode}): {detail}")


def prepare_profiles(plans, dry_run=False, env=None):
    """Return ready profile paths after installed browsers initialize defaults.

    Missing browsers are errors here. The caller selects applications before
    planning, based on the installation mode and selected package manifests.
    A dry run returns only existing paths and never starts a browser.
    """
    ready = {}
    for plan in plans:
        label = APPLICATIONS[plan.application]
        if not plan.create:
            if not plan.path.is_dir():
                raise ValueError(f"{label} profile disappeared after planning: {plan.path}")
            ready[plan.application] = plan.path
            continue
        if dry_run:
            print(f"Would initialize {label}'s native default profile under {plan.root} (headless).")
            continue
        binary = shutil.which(plan.application)
        if not binary:
            raise ValueError(f"{label} is not installed; cannot initialize its default profile.")
        roots = profile_roots(plan.application, plan.home, plan.config)
        if discover_profile(plan.application, roots):
            raise ValueError(f"{label} profiles changed after planning; rerun the installer to select the current default.")
        environment = dict(os.environ if env is None else env)
        environment.update(HOME=str(plan.home), XDG_CONFIG_HOME=str(plan.config), MOZ_HEADLESS="1")
        # An alternate home must not inherit the caller's cache/data/state roots.
        if Path(os.environ.get("HOME", "")).absolute() != plan.home:
            for key, relative in (("XDG_CACHE_HOME", ".cache"),
                                  ("XDG_DATA_HOME", ".local/share"),
                                  ("XDG_STATE_HOME", ".local/state")):
                if env is None or key not in env:
                    environment[key] = str(plan.home / relative)
        plan.home.mkdir(parents=True, exist_ok=True)
        # -CreateProfile alone makes a legacy profile which modern Gecko does
        # not select on first launch. A normal headless blank-page startup
        # creates the correct dedicated default and exits after the screenshot.
        with tempfile.TemporaryDirectory(prefix="chase-arch-browser-") as temporary:
            screenshot = Path(temporary) / "blank.png"
            print(f"Initializing {label}'s native default profile without opening a window.")
            _initialize([binary, "--headless", "--no-remote", "--screenshot", str(screenshot),
                         "about:blank"], environment)
        found = discover_profile(plan.application, roots)
        if found is None:
            raise ValueError(f"{label} did not register a default profile; use --{plan.application}-profile PATH.")
        ready[plan.application] = found[1]
    return ready
