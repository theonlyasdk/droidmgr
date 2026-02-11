# droidmgr

A GUI frontend for scrcpy and device manager for Android written in Python using tkinter.

## Features

- **Device Management**: List and manage all connected Android devices
- **Screen Mirroring**: Start/stop screen mirroring using scrcpy
- **Process Management**: View and kill running processes on devices
- **App Management**: List, start, and stop installed applications
- **File Management**: Browse, download, upload, and delete files on devices
- **Auto-Setup**: Automatically downloads and installs ADB if not found
- **Native Theming**: Uses the native theming of your operating system

## Installation

### Prerequisites

The application uses only Python's standard library, but requires system dependencies:

1. **scrcpy** - For screen mirroring
   - Linux: `sudo apt install scrcpy`
   - macOS: `brew install scrcpy`
   - Windows: Download from [scrcpy releases](https://github.com/Genymobile/scrcpy/releases)

2. **ADB** - Will be downloaded automatically if not found

### Running

Simply execute the main entry point:

```bash
python3 droidmgr.py
```

Or make it executable:

```bash
chmod +x droidmgr.py
./droidmgr.py
```

## Usage

1. **Connect your Android device** via USB or WiFi ADB
2. **Enable USB debugging** in Developer Options on your device
3. **Run droidmgr**: `python3 droidmgr.py`
4. **Select a device** from the Devices tab
5. **Use the tabs** to manage processes, apps, or files
6. **Click "Start Mirroring"** to begin screen mirroring

## Development

The codebase is designed with clean separation:

- **Core modules** are UI-agnostic and can be used independently
- **UI modules** only handle presentation and user interaction
- **Threading** is used for long-running operations to keep UI responsive
- **Error handling** provides user-friendly messages for common issues

## License

All the code in this repository are released under the Mozilla Public License 2.0. See [LICENSE](LICENSE) file for details.
