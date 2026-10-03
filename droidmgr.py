#!/usr/bin/env python3
"""droidmgr - GUI frontend for scrcpy.

This is the main entry point for the application.
It automatically initializes and starts the UI.
"""

import sys
from pathlib import Path

# On Windows, ensure stdout/stderr handle UTF-8 symbols gracefully
if sys.platform.startswith('win'):
    try:
        if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

# Enable High DPI awareness before any GUI components are created
from ui import MainWindow, InitDialog, enable_dpi_awareness
enable_dpi_awareness()


def main():
    """Main entry point for droidmgr."""
    print("Starting droidmgr...")
    print("Checking dependencies...")
    
    # Try to get existing paths first
    from core import DependencyManager
    dep_manager = DependencyManager()
    
    adb_path = None
    scrcpy_path = None
    show_dialog = False
    
    try:
        adb_path = dep_manager.get_adb_path()
        print(f"✓ ADB found at: {adb_path}")
    except RuntimeError:
        print("✗ ADB not found")
        show_dialog = True
    
    try:
        scrcpy_path = dep_manager.get_scrcpy_path()
        print(f"✓ scrcpy found at: {scrcpy_path}")
    except RuntimeError:
        print("✗ scrcpy not found")
        show_dialog = True
    
    # Only show initialization dialog if dependencies are missing
    if show_dialog:
        print("Initializing missing dependencies...")
        init_dialog = InitDialog()
        success, adb_path, scrcpy_path = init_dialog.run()
        
        if not success:
            print("Initialization cancelled or failed.")
            return
    
    print("Starting UI...")
    app = MainWindow(adb_path, scrcpy_path)
    try:
        app.run()
    finally:
        import os
        os._exit(0)


if __name__ == '__main__':
    import signal
    
    def sigint_handler(signum, frame):
        print("\nKeyboardInterrupt received. Exiting droidmgr...", flush=True)
        sys.exit(0)
        
    signal.signal(signal.SIGINT, sigint_handler)
    
    try:
        main()
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received. Exiting droidmgr...", flush=True)
        sys.exit(0)


