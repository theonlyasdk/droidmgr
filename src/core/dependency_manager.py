"""Manages downloading and installing scrcpy and adb dependencies."""

import os
import platform
import shutil
import zipfile
import tarfile
from pathlib import Path
from typing import Optional
import urllib.request
from urllib.error import URLError


class DependencyManager:
    """Manages automatic download and installation of scrcpy and adb."""
    
    def __init__(self, install_dir: Optional[Path] = None):
        """Initialize the dependency manager.
        
        Args:
            install_dir: Directory to install dependencies. Defaults to ~/.droidmgr/bin
        """
        if install_dir is None:
            install_dir = Path.home() / '.droidmgr' / 'bin'
        
        self.install_dir = Path(install_dir)
        self.install_dir.mkdir(parents=True, exist_ok=True)
        
        self.system = platform.system().lower()
        self.machine = platform.machine().lower()
        
    def get_adb_path(self, auto_download=False, progress_callback=None) -> Path:
        """Get the path to the adb binary, downloading if necessary.
        
        Args:
            auto_download: If True, download without asking
            progress_callback: Optional callback function(current, total, status_msg)
        
        Returns:
            Path to adb executable
        """
        # Check if adb is already in PATH
        adb_in_path = shutil.which('adb')
        if adb_in_path:
            return Path(adb_in_path)
        
        # Check if we have it installed locally
        adb_name = 'adb.exe' if self.system == 'windows' else 'adb'
        local_adb = self.install_dir / 'platform-tools' / adb_name
        
        if local_adb.exists():
            return local_adb
        
        # Download and install
        if not auto_download:
            raise RuntimeError("ADB not found")
        
        self._download_adb(progress_callback)
        
        if local_adb.exists():
            return local_adb
        
        raise RuntimeError("Failed to download and install ADB")
    
    def get_scrcpy_path(self, auto_download=False, progress_callback=None) -> Path:
        """Get the path to the scrcpy binary, downloading if necessary.
        
        Args:
            auto_download: If True, download without asking
            progress_callback: Optional callback function(current, total, status_msg)
        
        Returns:
            Path to scrcpy executable
        """
        # Check if scrcpy is already in PATH
        scrcpy_in_path = shutil.which('scrcpy')
        if scrcpy_in_path:
            return Path(scrcpy_in_path)
        
        # Check if we have it installed locally
        scrcpy_name = 'scrcpy.exe' if self.system == 'windows' else 'scrcpy'
        local_scrcpy = self.install_dir / 'scrcpy' / scrcpy_name
        
        if local_scrcpy.exists():
            return local_scrcpy
        
        # Download and install
        if not auto_download:
            raise RuntimeError("scrcpy not found")
        
        self._download_scrcpy(progress_callback)
        
        if local_scrcpy.exists():
            return local_scrcpy
        
        raise RuntimeError("Failed to download and install scrcpy")
    
    def _download_adb(self, progress_callback=None) -> None:
        """Download and extract platform-tools (adb).
        
        Args:
            progress_callback: Optional callback function(current, total, status_msg)
        """
        # Platform-tools download URLs
        urls = {
            'linux': 'https://dl.google.com/android/repository/platform-tools-latest-linux.zip',
            'darwin': 'https://dl.google.com/android/repository/platform-tools-latest-darwin.zip',
            'windows': 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip'
        }
        
        url = urls.get(self.system)
        if not url:
            raise RuntimeError(f"Unsupported platform: {self.system}")
        
        download_path = self.install_dir / 'platform-tools.zip'
        
        try:
            if progress_callback:
                progress_callback(0, 100, "Downloading ADB...")
            
            # Download with progress
            def reporthook(block_num, block_size, total_size):
                if progress_callback and total_size > 0:
                    downloaded = block_num * block_size
                    percent = min(int((downloaded / total_size) * 90), 90)  # 0-90%
                    progress_callback(percent, 100, f"Downloading ADB: {percent}%")
            
            urllib.request.urlretrieve(url, download_path, reporthook=reporthook)
            
            if progress_callback:
                progress_callback(90, 100, "Extracting ADB...")
            
            with zipfile.ZipFile(download_path, 'r') as zip_ref:
                zip_ref.extractall(self.install_dir)
            
            # Make executables
            if self.system != 'windows':
                adb_path = self.install_dir / 'platform-tools' / 'adb'
                adb_path.chmod(0o755)
            
            download_path.unlink()
            
            if progress_callback:
                progress_callback(100, 100, "ADB installed successfully!")
            
        except Exception as e:
            raise RuntimeError(f"Failed to download ADB: {e}")
    
    def _download_scrcpy(self, progress_callback=None) -> None:
        """Download and extract scrcpy.
        
        Args:
            progress_callback: Optional callback function(current, total, status_msg)
        """
        # First check common installation paths
        common_paths = []
        
        if self.system == 'linux':
            common_paths = [
                Path('/usr/bin/scrcpy'),
                Path('/usr/local/bin/scrcpy'),
                Path.home() / '.local/bin/scrcpy'
            ]
        elif self.system == 'darwin':
            common_paths = [
                Path('/usr/local/bin/scrcpy'),
                Path('/opt/homebrew/bin/scrcpy')
            ]
        elif self.system == 'windows':
            common_paths = [
                Path('C:/Program Files/scrcpy/scrcpy.exe'),
                Path('C:/scrcpy/scrcpy.exe')
            ]
        
        for path in common_paths:
            if path.exists():
                # Create a symlink or copy
                target = self.install_dir / 'scrcpy' / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                
                try:
                    os.symlink(path, target)
                except OSError:
                    shutil.copy2(path, target)
                
                if progress_callback:
                    progress_callback(100, 100, "scrcpy found in system!")
                return
        
        # Download scrcpy
        # Note: scrcpy releases are platform-specific
        # Using a recent stable version (v2.3.1 as of writing)
        version = "2.3.1"
        
        urls = {
            'linux': f'https://github.com/Genymobile/scrcpy/releases/download/v{version}/scrcpy-linux-v{version}.tar.gz',
            'windows': f'https://github.com/Genymobile/scrcpy/releases/download/v{version}/scrcpy-win64-v{version}.zip',
        }
        
        # macOS typically uses homebrew, but we can provide instructions
        if self.system == 'darwin':
            raise RuntimeError(
                "Please install scrcpy using Homebrew:\n"
                "  brew install scrcpy\n\n"
                "Or download manually from:\n"
                "  https://github.com/Genymobile/scrcpy/releases"
            )
        
        url = urls.get(self.system)
        if not url:
            raise RuntimeError(f"Automatic download not supported for {self.system}")
        
        # Determine file extension
        is_zip = url.endswith('.zip')
        ext = '.zip' if is_zip else '.tar.gz'
        download_path = self.install_dir / f'scrcpy{ext}'
        
        try:
            if progress_callback:
                progress_callback(0, 100, "Downloading scrcpy...")
            
            # Download with progress
            def reporthook(block_num, block_size, total_size):
                if progress_callback and total_size > 0:
                    downloaded = block_num * block_size
                    percent = min(int((downloaded / total_size) * 90), 90)  # 0-90%
                    progress_callback(percent, 100, f"Downloading scrcpy: {percent}%")
            
            urllib.request.urlretrieve(url, download_path, reporthook=reporthook)
            
            if progress_callback:
                progress_callback(90, 100, "Extracting scrcpy...")
            
            # Extract
            scrcpy_dir = self.install_dir / 'scrcpy'
            scrcpy_dir.mkdir(parents=True, exist_ok=True)
            
            if is_zip:
                with zipfile.ZipFile(download_path, 'r') as zip_ref:
                    zip_ref.extractall(self.install_dir)
            else:
                with tarfile.open(download_path, 'r:gz') as tar_ref:
                    tar_ref.extractall(self.install_dir)
            
            # Find the scrcpy executable in extracted files
            for root, dirs, files in os.walk(self.install_dir):
                for file in files:
                    if file == 'scrcpy' or file == 'scrcpy.exe':
                        src = Path(root) / file
                        dst = scrcpy_dir / file
                        
                        # Move/copy the executable
                        if not dst.exists():
                            shutil.move(str(src), str(dst))
                        
                        # Make executable on Unix
                        if self.system != 'windows':
                            dst.chmod(0o755)
                        
                        break
            
            # Cleanup
            download_path.unlink()
            
            if progress_callback:
                progress_callback(100, 100, "scrcpy installed successfully!")
            
        except Exception as e:
            raise RuntimeError(f"Failed to download scrcpy: {e}")
    
    def verify_dependencies(self) -> tuple[bool, bool]:
        """Verify that both adb and scrcpy are available.
        
        Returns:
            Tuple of (adb_available, scrcpy_available)
        """
        adb_available = False
        scrcpy_available = False
        
        try:
            self.get_adb_path()
            adb_available = True
        except RuntimeError:
            pass
        
        try:
            self.get_scrcpy_path()
            scrcpy_available = True
        except RuntimeError:
            pass
        
        return adb_available, scrcpy_available
