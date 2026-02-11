#!/usr/bin/env python3
"""droidmgr - GUI frontend for scrcpy.

This is the main entry point for the application.
It automatically initializes and starts the UI.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from ui import MainWindow, InitDialog


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
    app.run()


if __name__ == '__main__':
    main()
