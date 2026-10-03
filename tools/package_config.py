"""Shared configuration and utilities for the droidmgr packaging scripts."""

import os
import sys
import re
import zipfile
import platform
import subprocess
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# ─── Configuration ───────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "droidmgr"
SRC_DIR = PROJECT_ROOT / "src"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
SPEC_DIR = PROJECT_ROOT
OUTPUT_DIR = PROJECT_ROOT / "packages"

# PyInstaller hidden imports (modules loaded dynamically)
HIDDEN_IMPORTS = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.simpledialog",
]


# ─── Utilities ───────────────────────────────────────────────────────────────

def get_platform_info() -> dict:
    """Get platform-specific build info."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    # Normalise architecture names
    arch_map = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "x64": "x86_64",
        "i386": "x86",
        "i686": "x86",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    arch = arch_map.get(machine, machine)

    if system == "windows":
        return {
            "platform_tag": f"win-{arch}",
            "extension": ".exe",
            "icon": None,
            "windowed": True,
        }
    elif system == "darwin":
        return {
            "platform_tag": f"mac-{arch}",
            "extension": "",
            "icon": None,
            "windowed": True,
        }
    else:
        return {
            "platform_tag": f"linux-{arch}",
            "extension": "",
            "icon": None,
            "windowed": False,
        }


def get_version() -> str:
    """Extract version from project metadata. Falls back to '0.0.0'."""
    version_file = PROJECT_ROOT / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()

    # Try to read from __init__.py
    init_file = Path(SRC_DIR) / "__init__.py"
    if init_file.exists():
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_file.read_text())
        if match:
            return match.group(1)

    return "0.0.0"


def format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


def sha256_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def check_upx() -> Optional[str]:
    """Check if UPX is available for optional compression."""
    upx = shutil.which("upx")
    if upx:
        try:
            result = subprocess.run([upx, "--version"], capture_output=True, text=True, timeout=10)
            version_line = result.stdout.splitlines()[0] if result.stdout else "unknown"
            print(f"  ✓ UPX found: {version_line}")
            return upx
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    print("  - UPX not found (optional, speeds up final executable compression)")
    return None
