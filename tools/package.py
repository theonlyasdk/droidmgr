#!/usr/bin/env python3
"""
Packaging script for droidmgr
Builds standalone executables with PyInstaller and creates an optimized ZIP archive.
"""
import platform
import sys
try:
    from .package_config import get_platform_info, get_version
    from .package_config import (
        APP_NAME, BUILD_DIR, DIST_DIR, HIDDEN_IMPORTS, OUTPUT_DIR,
        PROJECT_ROOT, SPEC_DIR, SRC_DIR, check_upx, format_size, sha256_hash,
    )
    from .package_build import build_executable, check_pyinstaller
    from .package_archive import cleanup, create_optimized_zip
except ImportError:
    from package_config import get_platform_info, get_version
    from package_config import (
        APP_NAME, BUILD_DIR, DIST_DIR, HIDDEN_IMPORTS, OUTPUT_DIR,
        PROJECT_ROOT, SPEC_DIR, SRC_DIR, check_upx, format_size, sha256_hash,
    )
    from package_build import build_executable, check_pyinstaller
    from package_archive import cleanup, create_optimized_zip


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
