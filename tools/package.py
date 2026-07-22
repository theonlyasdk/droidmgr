#!/usr/bin/env python3
"""
Packaging script for droidmgr
Builds standalone executables with PyInstaller and creates an optimized ZIP archive.
"""

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


# ─── Step 1: PyInstaller Build ───────────────────────────────────────────────

def check_pyinstaller() -> bool:
    """Ensure PyInstaller is installed."""
    try:
        import PyInstaller  # noqa: F401
        print("  ✓ PyInstaller is installed")
        return True
    except ImportError:
        print("  ✗ PyInstaller not found, installing via pip...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "pyinstaller"],
                check=True, capture_output=True, timeout=120,
            )
            print("  ✓ PyInstaller installed successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"  ✗ Failed to install PyInstaller: {e}")
            return False


def build_executable(use_upx: bool = True, strip: bool = True) -> bool:
    """Run PyInstaller to build a standalone executable."""
    os.chdir(PROJECT_ROOT)
    info = get_platform_info()

    cmd = [
        "pyinstaller",
        "--name", APP_NAME,
        "--onefile",
        "--clean",
        "--noconfirm",
        "--log-level", "INFO",
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
        f"--specpath={SPEC_DIR}",
        f"--paths={SRC_DIR}",
        "--collect-all", "src.core",
        "--collect-all", "src.ui",
    ]

    # Windowed vs console
    if info["windowed"]:
        cmd.append("--windowed")
    else:
        cmd.append("--console")

    # Stripping debug info
    if strip and info["platform_tag"].startswith("linux"):
        cmd.append("--strip")

    # UPX compression
    if use_upx:
        upx_path = check_upx()
        if upx_path:
            cmd.append(f"--upx-dir={Path(upx_path).parent}")
            cmd.append("--upx-exclude=vcruntime140.dll")  # avoid UPX-broken DLL

    # Icon
    if info["icon"] and Path(info["icon"]).exists():
        cmd.append(f"--icon={info['icon']}")

    # Hidden imports
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])

    # Main entry point
    cmd.append(str(PROJECT_ROOT / "droidmgr.py"))

    print(f"  Command: pyinstaller ... (see below for full log)")
    # Show condensed flags
    for flag in cmd[1:]:
        if flag.startswith("--"):
            val = ""
            parts = flag.split("=", 1)
            if len(parts) == 2:
                flag, val = parts
            print(f"    {flag} {val}".strip())

    print()
    try:
        subprocess.run(cmd, check=True)
        print()
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n  ✗ PyInstaller failed with exit code {e.returncode}")
        return False


# ─── Step 2: Create Optimized ZIP ────────────────────────────────────────────

def create_optimized_zip(version: str, platform_tag: str) -> Optional[Path]:
    """Create an optimized ZIP archive with maximum compression."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    info = get_platform_info()
    exe_name = f"{APP_NAME}{info['extension']}"
    exe_path = DIST_DIR / exe_name

    if not exe_path.exists():
        print(f"  ✗ Executable not found: {exe_path}")
        return None

    # Determine archive name
    timestamp = datetime.now().strftime("%Y%m%d")
    archive_name = f"{APP_NAME}-v{version}-{platform_tag}-{timestamp}.zip"
    archive_path = OUTPUT_DIR / archive_name

    print(f"  Archive: {archive_path.name}")
    print(f"  Compression: DEFLATED (level 9)")

    exe_size = exe_path.stat().st_size
    print(f"  Executable size: {format_size(exe_size)}")

    # Write the ZIP with maximum compression
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # Store executable at the root of the archive
        zf.write(exe_path, arcname=exe_name)

        # Also include a README.txt
        readme_text = f"""
╔══════════════════════════════════════════════════════════╗
║  {APP_NAME} v{version}                                   ║
║  Platform: {platform_tag}                                 ║
║  Built:    {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}           ║
╚══════════════════════════════════════════════════════════╝

Prerequisites:
  - scrcpy (for screen mirroring): https://github.com/Genymobile/scrcpy
  - Android device with USB debugging enabled

Run:
  {exe_name}

SHA-256: {sha256_hash(exe_path)}

"""
        zf.writestr(f"{APP_NAME}_README.txt", readme_text.strip())

    zip_size = archive_path.stat().st_size
    saved = exe_size - zip_size
    ratio = (1 - zip_size / exe_size) * 100 if exe_size > 0 else 0

    print(f"  Archive size:   {format_size(zip_size)}")
    print(f"  Compression:    saved {format_size(saved)} ({ratio:.1f}% reduction)")

    return archive_path


# ─── Step 3: Cleanup ────────────────────────────────────────────────────────

def cleanup(keep_dist: bool = False):
    """Remove build artifacts."""
    print()
    print("  Cleaning build artifacts...")

    # Remove build directory
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
        print(f"  ✓ Removed: {BUILD_DIR}")

    # Remove .spec files
    for spec in PROJECT_ROOT.glob("*.spec"):
        spec.unlink()
        print(f"  ✓ Removed: {spec}")

    # Remove __pycache__ directories across the project
    for pycache in PROJECT_ROOT.glob("**/__pycache__"):
        if pycache.is_dir():
            shutil.rmtree(pycache)

    if not keep_dist:
        # Remove the standalone executable (keeping only the zip)
        info = get_platform_info()
        exe_name = f"{APP_NAME}{info['extension']}"
        exe_path = DIST_DIR / exe_name
        if exe_path.exists():
            exe_path.unlink()
            print(f"  ✓ Removed: {exe_path}")

    print("  ✓ Cleanup complete")


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 60)
    print(f"  {APP_NAME} Packaging Script")
    print("=" * 60)
    print()

    version = get_version()
    platform_info = get_platform_info()
    platform_tag = platform_info["platform_tag"]
    print(f"  App:      {APP_NAME} v{version}")
    print(f"  Platform: {platform_info['platform_tag']}")
    print(f"  Python:   {platform.python_version()}")
    print()

    # ── Step 1: Install / check PyInstaller ──
    print("[1/3] Checking PyInstaller...")
    if not check_pyinstaller():
        print("\n  ✗ Cannot proceed without PyInstaller.")
        sys.exit(1)
    print()

    # ── Step 2: Build executable ──
    print("[2/3] Building executable with PyInstaller...")
    if not build_executable(use_upx=True, strip=True):
        # Try again without UPX/strip in case they cause issues
        print("  Retrying without UPX compression...")
        if not build_executable(use_upx=False, strip=False):
            print("\n  ✗ Build failed.")
            sys.exit(1)
    print()

    # ── Step 3: Create optimized ZIP ──
    print("[3/3] Creating optimized ZIP archive...")
    archive_path = create_optimized_zip(version, platform_tag)
    if not archive_path:
        print("\n  ✗ Failed to create ZIP archive.")
        sys.exit(1)
    print()

    # ── Cleanup ──
    cleanup(keep_dist=False)

    # ── Summary ──
    print()
    print("-" * 60)
    print("  Packaging Complete!")
    print("-" * 60)
    print(f"  Archive: {archive_path}")
    print(f"  Size:    {format_size(archive_path.stat().st_size)}")
    print()

    # Generate checksums file
    checksum_path = archive_path.with_suffix(".sha256")
    with open(checksum_path, "w") as f:
        f.write(f"{sha256_hash(archive_path)}  {archive_path.name}\n")
    print(f"  Checksum: {checksum_path}")

    print()
    print("  To deploy, share the ZIP file and the .sha256 checksum.")
    print("  Recipients just need to extract and run the executable.")
    print()
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
