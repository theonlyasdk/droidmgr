"""Icon asset helpers shared by the tile grids."""

import sys
import tkinter as tk
from pathlib import Path


def find_asset(filename: str) -> Optional[str]:
    """Locate a bundled asset, working both from source and PyInstaller."""
    here = Path(__file__).resolve().parent
    candidates = [
        here / 'assets' / filename,
        here.parent / 'assets' / filename,
        Path(getattr(sys, '_MEIPASS', '')) / 'assets' / filename,
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except Exception:
            continue
    return None

def load_scaled_icon(path: Optional[str], target_px: int, widget: tk.Misc) -> Optional[tk.PhotoImage]:
    """Load an image file scaled down to about target_px via subsample.

    PhotoImage subsampling is integer-only, so the result is approximate
    (e.g. 256px -> ~51px for a 48px target). Returns None when the file
    is missing or unreadable, letting the caller skip the image item.
    """
    if not path:
        return None
    try:
        raw = tk.PhotoImage(file=path)
    except Exception:
        return None
    try:
        width = raw.width()
        if width > target_px:
            sub = max(1, round(width / target_px))
            if sub > 1:
                return raw.subsample(sub, sub)
        return raw
    except Exception:
        return raw

