# Droidmgr Build Tools

This directory contains tools for building and deploying droidmgr.

## Build Script

The `build.py` script creates standalone executables for different platforms:

### Prerequisites

- **Linux (Arch-based)**: Automatically installs PyInstaller via `pacman`
- **Other systems**: Automatically installs PyInstaller via `pip`

### Usage

```bash
# From the project root directory
python3 tools/build.py

# Or make it executable and run directly
chmod +x tools/build.py
./tools/build.py
```

### What It Does

1. **Checks for PyInstaller**
   - On Arch Linux: Tries AUR helpers in order (yay, paru, pamac) to install `pyinstaller`
   - Falls back to `pip install pyinstaller` if no AUR helper is found or if installation fails
   - On other systems: Uses `pip install pyinstaller`

2. **Builds the executable**
   - Windows: Creates `droidmgr.exe`
   - Linux: Creates `droidmgr` (executable binary)
   - macOS: Creates `droidmgr.app`

3. **Output Location**
   - All executables are placed in the `dist/` directory
   - Ready to distribute or run directly

4. **Optional Cleanup**
   - Removes build artifacts (`build/`, `__pycache__/`, `.spec` files)
   - Keeps only the final executable in `dist/`

### Platform-Specific Notes

**Linux:**
- Executable is created without extension
- Automatically set with execute permissions (755)
- Console mode (shows terminal output)

**Windows:**
- Creates `.exe` file
- Windowed mode (no console unless errors occur)

**macOS:**
- Creates `.app` bundle
- Windowed mode for native macOS experience

## Distributing

After building, you can:

1. **Run locally**: `./dist/droidmgr`
2. **Copy to system**: `sudo cp dist/droidmgr /usr/local/bin/`
3. **Share with others**: Package the `dist/droidmgr` file
