"""Shared helpers for screenshot and screen recording."""

import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import messagebox


def open_path(path) -> bool:
    """Open a file with the OS default application. Returns False if that failed."""
    path = str(path)
    try:
        if os.name == 'nt':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
        return True
    except Exception:
        return False


def _timestamp() -> str:
    return datetime.now().strftime('%Y%m%d-%H%M%S')


def _default_dir(kind: str) -> Path:
    if kind == 'screenshot':
        folder = 'Pictures'
    elif kind == 'record':
        folder = 'Videos'
    else:
        folder = 'Downloads'
    return Path.home() / folder / 'droidmgr'


def _existing_dir(configured: str, fallback: Path) -> str:
    for candidate in (configured, str(fallback)):
        if candidate and Path(candidate).is_dir():
            return candidate
    return str(Path.home())


def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


# -- screenshot ------------------------------------------------------------


def remember_folder(root, config, key, label, saved_path, set_status, show_info,
                    note: str = '') -> None:
    """Announce a saved file and offer to remember its folder as the default.

    `key` is the `capture` config key holding the remembered folder, so each
    feature keeps its own default: screenshot_dir, record_dir, apk_dir.
    `note` is appended to the dialog when there is something extra to say.
    """
    saved_path = str(saved_path)
    folder = str(Path(saved_path).parent)
    set_status(f"{label} saved to {saved_path}")
    if str(config.get('capture', key, '')) == folder:
        show_info(f"{label} saved to:\n{saved_path}{note}")
        return
    if messagebox.askyesno(
            f"{label} Saved",
            f"Saved to:\n{saved_path}\n\nRemember '{folder}' as the default "
            f"{label.lower()} folder?{note}",
            parent=root):
        config.set('capture', key, folder)
