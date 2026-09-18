"""
Filesystem locations for Dalal AI.

The user-data directory is resolved once, defensively.  ``~/Documents`` is not
guaranteed to exist or be writable on a fresh Windows install: it is commonly
redirected into OneDrive, and on a locked-down or roaming profile creating it
can fail outright.  That mattered more than it looks — ``utils.logger`` calls
``get_logs_dir()`` at *import* time, so an unwritable Documents folder killed
the app during module import, before ``run_ui.main()``'s error handler existed
to show a dialog.  The app simply did nothing when double-clicked.
"""

from __future__ import annotations

import os
import sys
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

APP_NAME = "Dalal AI"
DOCUMENTS_FOLDER = "Documents"

_user_data_dir: str | None = None


def is_frozen() -> bool:
    """Check if the application is running as a PyInstaller bundle."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_bundle_dir() -> str:
    """Return the base directory of the bundled files or the project root."""
    if is_frozen():
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _candidate_data_dirs() -> list[str]:
    """User-data locations to try, best first."""
    home = str(Path.home())
    candidates = [os.path.join(home, DOCUMENTS_FOLDER, APP_NAME)]

    # Redirected Documents (OneDrive) — where the user actually sees their files.
    for env_var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        onedrive = os.environ.get(env_var)
        if onedrive:
            candidates.append(os.path.join(onedrive, DOCUMENTS_FOLDER, APP_NAME))

    # Always-writable per-user application data.
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, APP_NAME))
    candidates.append(os.path.join(home, f".{APP_NAME.lower().replace(' ', '_')}"))

    # Last resort, so the app still starts rather than crashing on import.
    candidates.append(os.path.join(tempfile.gettempdir(), APP_NAME))
    return candidates


def _is_usable(directory: str) -> bool:
    """Whether *directory* exists (or can be made) and accepts a write."""
    try:
        os.makedirs(directory, exist_ok=True)
        probe = os.path.join(directory, ".write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def get_user_data_dir() -> str:
    """
    Return the writable per-user data folder, creating it if necessary.

    Resolved once and cached so every caller agrees on one location even if the
    first choice later becomes unavailable.
    """
    global _user_data_dir
    if _user_data_dir is not None:
        return _user_data_dir

    for candidate in _candidate_data_dirs():
        if _is_usable(candidate):
            _user_data_dir = candidate
            return _user_data_dir

    # Nothing was writable; fall back to the CWD so callers still get a path.
    _user_data_dir = os.path.abspath(".")
    return _user_data_dir


def _subdir(name: str) -> str:
    path = os.path.join(get_user_data_dir(), name)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return get_user_data_dir()
    return path


def get_logs_dir() -> str:
    """Return the path to the logs directory inside user data."""
    return _subdir("logs")


def get_attachments_dir() -> str:
    """Return the path to the attachments directory inside user data."""
    return _subdir("attachments")


def get_config_path() -> str:
    """Return the path to the user's config.yaml file."""
    return os.path.join(get_user_data_dir(), "config.yaml")


def get_history_path() -> str:
    """Return the path to the user's chat_history.json file."""
    return os.path.join(get_user_data_dir(), "chat_history.json")


# Sections that belong to the user and survive a config refresh.  Everything
# else — `platforms` above all — is shipped with the build.
_USER_OWNED_SECTIONS = ("browser", "timing", "context", "export_directory")


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Return *base* with *overlay*'s values applied, recursing into dicts."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _backup_config(user_config: str) -> None:
    """Keep a timestamped copy so a refresh can never lose the user's edits."""
    try:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(user_config, f"{user_config}.{stamp}.bak")
    except OSError:
        pass


def init_user_data() -> None:
    """
    Make sure the user's config exists and its platform selectors are current.

    The config is copied into the user's data folder on first run so it can be
    edited.  The catch: it was then never touched again, so a selector fix
    shipped in a later build only ever reached brand-new installs.  Anyone who
    had run the app once kept the stale selectors forever and saw the same DOM
    failure after upgrading.

    `platforms` is therefore treated as code and refreshed from the bundle
    whenever the bundled `config_version` is newer, while the user's own
    browser/timing/context settings are merged back on top and the previous file
    is backed up.
    """
    user_config = get_config_path()
    bundled_config = os.path.join(get_bundle_dir(), "config.yaml")

    if not os.path.exists(bundled_config):
        print(f"Warning: Default config not found at {bundled_config}")
        return

    if not os.path.exists(user_config):
        try:
            shutil.copy2(bundled_config, user_config)
            print(f"Copied default config to {user_config}")
        except OSError as exc:
            print(f"Warning: could not create {user_config}: {exc}")
        return

    try:
        import yaml
        with open(bundled_config, "r", encoding="utf-8") as fh:
            bundled = yaml.safe_load(fh) or {}
        try:
            with open(user_config, "r", encoding="utf-8") as fh:
                current = yaml.safe_load(fh) or {}
            if not isinstance(current, dict):
                raise ValueError("config root must be a mapping")
        except (yaml.YAMLError, ValueError, OSError) as exc:
            # Unreadable user config: keep it aside and start from the bundle.
            print(f"Warning: {user_config} is unreadable ({exc}); resetting it.")
            _backup_config(user_config)
            shutil.copy2(bundled_config, user_config)
            return

        bundled_version = int(bundled.get("config_version", 0) or 0)
        current_version = int(current.get("config_version", 0) or 0)
        if bundled_version <= current_version:
            return

        merged = dict(bundled)
        for section in _USER_OWNED_SECTIONS:
            if section not in current:
                continue
            if isinstance(current[section], dict) and isinstance(merged.get(section), dict):
                merged[section] = _deep_merge(merged[section], current[section])
            else:
                merged[section] = current[section]
        merged["config_version"] = bundled_version

        _backup_config(user_config)
        tmp_path = f"{user_config}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(merged, fh, sort_keys=False, allow_unicode=True)
        os.replace(tmp_path, user_config)
        print(
            f"Updated {user_config} to config_version {bundled_version} "
            f"(your browser/timing settings were kept; a .bak was saved)."
        )
    except Exception as exc:
        # Never let a config refresh stop the app from starting.
        print(f"Warning: could not refresh {user_config}: {exc}")
