#!/usr/bin/env python3
"""
Deployment script for droidmgr
Creates standalone executables for different platforms using PyInstaller
"""

import os
import sys
import platform
import subprocess
import shutil
from pathlib import Path

def check_pyinstaller():
    """Check if PyInstaller is installed, install if not."""
    try:
        import PyInstaller
        print("✓ PyInstaller is already installed")
        return True
    except ImportError:
        print("✗ PyInstaller not found")
        
        system = platform.system().lower()
        
        if system == 'linux':
            # Check if we're on Arch-based system (PyInstaller is in AUR)
            if shutil.which('pacman'):
                print("Detected Arch Linux - PyInstaller is in the AUR")
                
                # Try common AUR helpers in order of preference
                aur_helpers = ['yay', 'paru', 'pamac']
                helper_found = None
                
                for helper in aur_helpers:
                    if shutil.which(helper):
                        helper_found = helper
                        break
                
                if helper_found:
                    print(f"Installing PyInstaller via {helper_found}...")
                    try:
                        subprocess.run([helper_found, '-S', '--noconfirm', 'pyinstaller'], check=True)
                        print("✓ PyInstaller installed successfully")
                        return True
                    except subprocess.CalledProcessError:
                        print(f"Failed to install via {helper_found}, trying pip...")
                else:
                    print("No AUR helper found (yay, paru, pamac)")
                    print("Please install an AUR helper or run: pip install pyinstaller")
                    print("Trying pip as fallback...")
            
            # Fallback to pip
            try:
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'], check=True)
                print("✓ PyInstaller installed successfully via pip")
                return True
            except subprocess.CalledProcessError:
                print("✗ Failed to install PyInstaller")
                return False
        else:
            # For Windows/Mac, use pip
            try:
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'], check=True)
                print("✓ PyInstaller installed successfully")
                return True
            except subprocess.CalledProcessError:
                print("✗ Failed to install PyInstaller")
                return False

def get_platform_info():
    """Get platform-specific information."""
    system = platform.system().lower()
    
    if system == 'windows':
        return {
            'name': 'Windows',
            'extension': '.exe',
            'icon': None,  # Add .ico file path if you have one
            'separator': ';'
        }
    elif system == 'darwin':
        return {
            'name': 'macOS',
            'extension': '.app',
            'icon': None,  # Add .icns file path if you have one
            'separator': ':'
        }
    else:  # Linux and others
        return {
            'name': 'Linux',
            'extension': '',
            'icon': None,  # Add .png file path if you have one
            'separator': ':'
        }

def build_executable():
    """Build the executable using PyInstaller."""
    # Get project root
    project_root = Path(__file__).parent.parent
    
    # Navigate to project root
    os.chdir(project_root)
    
    print(f"Building from: {project_root}")
    
    platform_info = get_platform_info()
    print(f"Target platform: {platform_info['name']}")
    
    # PyInstaller command
    cmd = [
        'pyinstaller',
        '--name=droidmgr',
        '--onefile',  # Single executable file
        '--windowed' if platform_info['name'] != 'Linux' else '--console',  # GUI mode for Windows/Mac
        '--clean',
        '--noconfirm',
        f'--paths={project_root / "src"}',  # Add src to Python path
        '--collect-all=ui',  # Collect all ui modules
        '--collect-all=core',  # Collect all core modules
    ]
    
    # Add icon if available
    if platform_info['icon'] and Path(platform_info['icon']).exists():
        cmd.append(f"--icon={platform_info['icon']}")
    
    # Add hidden imports for dynamic imports
    hidden_imports = [
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.simpledialog',
    ]
    
    for imp in hidden_imports:
        cmd.extend(['--hidden-import', imp])
    
    # Main script
    cmd.append('droidmgr.py')
    
    print("\nRunning PyInstaller...")
    print(f"Command: {' '.join(cmd)}\n")
    
    try:
        subprocess.run(cmd, check=True)
        print("\n✓ Build completed successfully!")
        
        # Show output location
        dist_dir = project_root / 'dist'
        executable_name = f"droidmgr{platform_info['extension']}"
        executable_path = dist_dir / executable_name
        
        if executable_path.exists():
            print(f"\n✓ Executable created at: {executable_path}")
            print(f"  Size: {executable_path.stat().st_size / (1024*1024):.2f} MB")
            
            # Make executable on Linux/Mac
            if platform_info['name'] in ['Linux', 'macOS']:
                os.chmod(executable_path, 0o755)
                print(f"  Permissions set to executable")
        else:
            print(f"\n⚠ Executable not found at expected location: {executable_path}")
            print(f"   Check the dist/ directory manually")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"\n✗ Build failed: {e}")
        return False

def clean_build_artifacts():
    """Clean up build artifacts."""
    project_root = Path(__file__).parent.parent
    
    artifacts = ['build', '__pycache__', '*.spec']
    
    print("\nCleaning build artifacts...")
    for pattern in artifacts:
        if '*' in pattern:
            for path in project_root.glob(f"**/{pattern}"):
                if path.is_file():
                    path.unlink()
                    print(f"  Removed: {path}")
        else:
            path = project_root / pattern
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                print(f"  Removed: {path}")
    
    print("✓ Cleanup complete")

def main():
    """Main deployment function."""
    print("=" * 60)
    print("  Droidmgr Deployment Script")
    print("=" * 60)
    print()
    
    # Check/Install PyInstaller
    if not check_pyinstaller():
        print("\n✗ Cannot proceed without PyInstaller")
        sys.exit(1)
    
    print()
    
    # Build executable
    if not build_executable():
        print("\n✗ Deployment failed")
        sys.exit(1)
    
    # Optional cleanup
    response = input("\nClean up build artifacts? (y/N): ").lower()
    if response == 'y':
        clean_build_artifacts()
    
    print("\n" + "=" * 60)
    print("  Deployment Complete!")
    print("=" * 60)
    print("\nYou can find your executable in the 'dist/' directory")
    print("Run it directly or distribute it to users.\n")

if __name__ == '__main__':
    main()
