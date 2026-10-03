"""Android keycodes and Win32 constants for the scrcpy overlay toolbar."""


# Android Keycodes
KEYCODE_HOME = 3
KEYCODE_BACK = 4
KEYCODE_VOLUME_UP = 24
KEYCODE_VOLUME_DOWN = 25
KEYCODE_POWER = 26
KEYCODE_APP_SWITCH = 187
KEYCODE_WAKEUP = 224
KEYCODE_SLEEP = 223
KEYCODE_PASTE = 279

# Win32 Virtual Key Codes
VK_LMENU = 0xA4       # Left Alt (Scrcpy MOD key)
VK_ESCAPE = 0x1B      # Escape (Scrcpy Back)
VK_HOME = 0x24        # Home (Scrcpy Home)
VK_UP = 0x26          # Up Arrow
VK_DOWN = 0x28        # Down Arrow
VK_B = 0x42           # B (MOD+b = Back)
VK_H = 0x48           # H (MOD+h = Home)
VK_P = 0x50           # P (MOD+p = Power)
VK_R = 0x52           # R (MOD+r = Rotate)
VK_S = 0x53           # S (MOD+s = Recents/App Switch)
VK_V = 0x56           # V (MOD+v = Paste computer clipboard)

KEYEVENTF_KEYUP = 0x0002

# Win32 Constants
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
