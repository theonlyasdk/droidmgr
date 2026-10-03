"""PyInstaller executable build step for the droidmgr packaging script."""

import os
import subprocess
import sys
from pathlib import Path
try:
    from .package_config import (
        APP_NAME, BUILD_DIR, DIST_DIR, HIDDEN_IMPORTS, PROJECT_ROOT, SPEC_DIR,
        SRC_DIR, check_upx, get_platform_info,
    )
except ImportError:
    from package_config import (
        APP_NAME, BUILD_DIR, DIST_DIR, HIDDEN_IMPORTS, PROJECT_ROOT, SPEC_DIR,
        SRC_DIR, check_upx, get_platform_info,
    )


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
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onefile",
        "--clean",
        "--noconfirm",
        "--log-level", "INFO",
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
        f"--specpath={SPEC_DIR}",
        f"--paths={SRC_DIR}",
        "--collect-all", "core",
        "--collect-all", "ui",
    ]

    sep = ";" if os.name == "nt" else ":"
    assets_dir = SRC_DIR / "assets"
    if assets_dir.exists():
        cmd.append(f"--add-data={assets_dir}{sep}assets")
    ui_assets_dir = SRC_DIR / "ui" / "assets"
    if ui_assets_dir.exists():
        cmd.append(f"--add-data={ui_assets_dir}{sep}ui/assets")

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

    # Add high DPI manifest for Windows
    manifest_path = PROJECT_ROOT / "tools" / "app.manifest"
    if info["platform_tag"].startswith("win") and manifest_path.exists():
        cmd.append(f"--manifest={manifest_path}")

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
