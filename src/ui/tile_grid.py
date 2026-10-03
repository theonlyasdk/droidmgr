"""Shared canvas tile-grid used by the Applications and Files tabs.

Both tabs show the same app-drawer style grid: a white canvas with one
selection/hover box, one icon and one truncated label per item. The widget
owns layout, hover, selection highlight, keyboard navigation, resize
relayout and viewport tracking. Callers only supply items, icons and three
small callbacks, so no grid logic is duplicated between tabs.

Performance notes (checked after implementation):
- Visible-key tracking uses row math, not one canvas bbox call per item,
  so scrolling stays O(1) Tk round-trips instead of O(N).
- Resize is debounced and relayouts with coords() instead of recreating
  canvas items, so no flicker and no per-resize allocation churn.
- Icon images are stored once in a dict; canvas items reference them, so
  nothing is garbage-collected mid-scroll and nothing leaks beyond the
  item count.
- All after() timers are cancelled on clear/destroy, and every deferred
  callback guards winfo_exists(), so no timer outlives the widget.
"""

import sys
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .dpi import scale_size
from .tile_assets import find_asset, load_scaled_icon
from .tile_render import _TileRenderMixin
from .tile_input import _TileInputMixin






class TileGrid(_TileRenderMixin, _TileInputMixin, ttk.Frame):
    """A multi-select canvas tile grid with shared layout behaviour.

    Selection follows the file-explorer model and is always reported in
    grid order: plain click selects one, Ctrl-click toggles, Shift-click
    extends a range from the anchor, dragging draws a rubber band, and
    Shift+arrows extend from the keyboard.
    """

    def __init__(self, parent, tile_w: int = 100, tile_h: int = 105,
                 icon_size: int = 48, margin: int = 10,
                 on_select: Optional[Callable[[Optional[str]], None]] = None,
                 on_activate: Optional[Callable[[Optional[str]], None]] = None,
                 on_context: Optional[Callable[[object, Optional[str]], None]] = None,
                 on_visible: Optional[Callable[[List[str]], None]] = None,
                 empty_text: str = "No items"):
        super().__init__(parent)
        self._base_tile_w = tile_w
        self._base_tile_h = tile_h
        self._base_icon = icon_size
        self._base_margin = margin
        self._on_select = on_select
        self._on_activate = on_activate
        self._on_context = on_context
        self._on_visible = on_visible

        self._items: List[Tuple[str, str]] = []
        self._keys: List[str] = []
        self._key_items: Dict[str, Tuple[int, int, int]] = {}
        self._item_key: Dict[int, str] = {}
        self._icons: Dict[str, tk.PhotoImage] = {}
        self._default_icon: Optional[tk.PhotoImage] = None
        self._selected: List[str] = []
        self._anchor: Optional[str] = None
        self._focus: Optional[str] = None
        self._hovered: Optional[str] = None
        self._cols = 1
        self._press_xy = None
        self._press_key: Optional[str] = None
        self._band_start = None
        self._band_rect: Optional[int] = None
        self._band_active = False
        self._skeleton = False
        self._skel_items: list = []
        self._skel_phase = False
        self._shimmer_after: Optional[str] = None
        self._fade_after: Optional[str] = None
        self._fade_snapshot = None
        self._focus_rect: Optional[int] = None
        self._resize_after: Optional[str] = None
        self._visible_after: Optional[str] = None
        self._closed = False

        self.canvas = tk.Canvas(
            self, borderwidth=0, highlightthickness=0, background="#ffffff",
            takefocus=True)
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL,
                                       command=self._on_scrollbar)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._empty_label = ttk.Label(
            self.canvas, text=empty_text, foreground='gray',
            background='#ffffff', anchor='center', justify='center')
        self._empty_label.place_forget()

        self.canvas.bind('<Configure>', self._on_configure)
        self.canvas.bind('<MouseWheel>', self._on_wheel)
        # Button-4/5: Linux wheel, harmless no-ops on Windows.
        self.canvas.bind('<Button-4>', self._on_wheel_up)
        self.canvas.bind('<Button-5>', self._on_wheel_down)
        self.canvas.bind('<ButtonPress-1>', self._on_press)
        self.canvas.bind('<B1-Motion>', self._on_drag_motion)
        self.canvas.bind('<ButtonRelease-1>', self._on_release)
        self.canvas.tag_bind("tile", "<Double-1>", self._on_tile_double)
        self.canvas.bind('<Motion>', self._on_motion)
        self.canvas.bind('<Leave>', self._on_leave)
        self.canvas.bind('<Button-3>', self._on_right_click)
        self.canvas.bind('<Key-Left>', lambda e: self._move(-1, 0))
        self.canvas.bind('<Key-Right>', lambda e: self._move(1, 0))
        self.canvas.bind('<Key-Up>', lambda e: self._move(0, -1))
        self.canvas.bind('<Key-Down>', lambda e: self._move(0, 1))
        self.canvas.bind('<Shift-Left>', lambda e: self._move(-1, 0, extend=True))
        self.canvas.bind('<Shift-Right>', lambda e: self._move(1, 0, extend=True))
        self.canvas.bind('<Shift-Up>', lambda e: self._move(0, -1, extend=True))
        self.canvas.bind('<Shift-Down>', lambda e: self._move(0, 1, extend=True))
        self.canvas.bind('<Home>', lambda e: self._go_to(0))
        self.canvas.bind('<Shift-Home>', lambda e: self._go_to(0, extend=True))
        self.canvas.bind('<Prior>', lambda e: self._move_page(-1))
        self.canvas.bind('<Shift-Prior>', lambda e: self._move_page(-1, extend=True))
        self.canvas.bind('<Next>', lambda e: self._move_page(1))
        self.canvas.bind('<Shift-Next>', lambda e: self._move_page(1, extend=True))
        self.canvas.bind('<End>', lambda e: self._go_to(-1))
        self.canvas.bind('<Shift-End>', lambda e: self._go_to(-1, extend=True))
        self.canvas.bind('<Escape>', self._cancel_band)
        self.canvas.bind('<Return>', lambda e: self._fire_activate())
        self.canvas.bind('<KP_Enter>', lambda e: self._fire_activate())
        self.canvas.bind('<space>', lambda e: self._fire_activate())
        self.bind('<Destroy>', self._on_destroy)

    # -- public API ----------------------------------------------------

    def set_empty_text(self, text: str):
        self._empty_label.config(text=text)
        self._update_empty()

    def set_default_icon(self, image: Optional[tk.PhotoImage]):
        # Stored only; the next set_items() render picks it up. This keeps
        # callers from paying for one render per setter before set_items().
        self._default_icon = image

    def set_items(self, items: List[Tuple[str, str]]):
        """Replace the grid contents. Selection is kept when still present."""
        if self._closed:
            return
        fade = getattr(self, '_skeleton', False)
        self.hide_skeleton()
        keep = set(k for k, _ in items)
        self._items = list(items)
        self._keys = [k for k, _ in self._items]
        self._selected = [k for k in self._selected if k in keep]
        if self._anchor not in keep:
            self._anchor = self._selected[-1] if self._selected else None
        if self._focus not in keep:
            self._focus = self._anchor
        self._hovered = None
        self._render(fade=fade)

    def clear(self):
        self.hide_skeleton()
        self._cancel(self._resize_after)
        self._cancel(self._visible_after)
        self._resize_after = self._visible_after = None
        self._items = []
        self._keys = []
        self._key_items = {}
        self._item_key = {}
        self._selected = []
        self._anchor = None
        self._focus = None
        self._hovered = None
        self._focus_rect = None
        try:
            self.canvas.delete("all")
        except Exception:
            pass
        self._update_empty()

    def update_icon(self, key: str, image: tk.PhotoImage):
        """Swap one tile's icon without a full re-render (async icon loads)."""
        if self._closed or image is None:
            return
        self._icons[key] = image  # hold a reference, else Tk blanks the tile
        try:
            if not self.canvas.winfo_exists():
                return
            trio = self._key_items.get(key)
            if trio:
                self.canvas.itemconfig(trio[1], image=image)
        except Exception:
            pass

    def set_icons(self, icons: Dict[str, tk.PhotoImage]):
        # Stored only; the next set_items() render picks them up.
        self._icons = dict(icons or {})

    def set_selected(self, keys) -> None:
        """Replace the selection (one key, a list, or None). No callback."""
        if keys is None:
            keys = []
        elif isinstance(keys, str):
            keys = [keys]
        valid = set(self._keys)
        self._selected = self._order([k for k in keys if k in valid])
        self._anchor = self._selected[-1] if self._selected else None
        self._focus = self._anchor
        # No fade cancel: programmatic sync must not kill a running crossfade.
        self._apply_selection(cancel_fade=False)

    def get_selected(self) -> List[str]:
        """Selected keys in grid order."""
        order = {k: i for i, k in enumerate(self._keys)}
        return sorted(self._selected, key=lambda k: order.get(k, len(order)))

    def get_focused(self) -> Optional[str]:
        """Focus key: what activate opens and ranges extend from."""
        if self._focus in self._keys:
            return self._focus
        if self._anchor in self._keys:
            return self._anchor
        return self._selected[-1] if self._selected else None

    def get_visible_keys(self) -> List[str]:
        """Keys in/near the viewport, via row math (no per-item bbox calls)."""
        if getattr(self, '_skeleton', False):
            return []
        if not self._keys or not self._canvas_alive():
            return []
        try:
            tile_h = self._tile_h()
            height = self.canvas.winfo_height() or tile_h
            top = self.canvas.canvasy(0) - tile_h
            bottom = self.canvas.canvasy(height) + tile_h
            if self._cols < 1:
                return []
            first_row = max(0, int(top // tile_h))
            last_row = int(bottom // tile_h)
            total_rows = (len(self._keys) + self._cols - 1) // self._cols
            last_row = min(last_row, total_rows - 1)
            if last_row < first_row:
                return []
            return self._keys[first_row * self._cols:(last_row + 1) * self._cols]
        except Exception:
            return []

    def scroll_to_key(self, key: str):
        if not self._canvas_alive():
            return
        trio = self._key_items.get(key)
        if not trio:
            return
        try:
            box = self.canvas.bbox(trio[0])
            region = self.canvas.cget("scrollregion").split()
            if not box or len(region) != 4:
                return
            top = self.canvas.canvasy(0)
            bottom = self.canvas.canvasy(self.canvas.winfo_height())
            if box[1] < top or box[3] > bottom:
                total = max(1.0, float(region[3]) - self.canvas.winfo_height())
                self.canvas.yview_moveto(max(0.0, min(1.0, (box[1] - 8) / total)))
        except Exception:
            pass

    def destroy(self):
        self._closed = True
        self.hide_skeleton()
        self._cancel(self._resize_after)
        self._cancel(self._visible_after)
        self._resize_after = self._visible_after = None
        super().destroy()

    # -- rendering -----------------------------------------------------

    def _tile_w(self) -> int:
        return scale_size(self._base_tile_w, self)

    def _tile_h(self) -> int:
        return scale_size(self._base_tile_h, self)

    def _margin(self) -> int:
        return scale_size(self._base_margin, self)

    def _icon_px(self) -> int:
        return scale_size(self._base_icon, self)

    def _canvas_alive(self) -> bool:
        try:
            return bool(self.canvas and self.canvas.winfo_exists())
        except Exception:
            return False

    def _cancel(self, after_id: Optional[str]):
        if after_id:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass


    # -- events --------------------------------------------------------


