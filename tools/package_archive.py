"""ZIP archive creation and cleanup steps for the droidmgr packaging script."""

import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional
try:
    from .package_config import (
        APP_NAME, BUILD_DIR, DIST_DIR, OUTPUT_DIR, PROJECT_ROOT,
        format_size, get_platform_info, sha256_hash,
    )
except ImportError:
    from package_config import (
        APP_NAME, BUILD_DIR, DIST_DIR, OUTPUT_DIR, PROJECT_ROOT,
        format_size, get_platform_info, sha256_hash,
    )


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
