"""TileGrid mixin: canvas layout, rendering and selection highlight."""

import tkinter as tk
from .dpi import scale_size


def _lerp_color(from_hex: str, to_hex: str, t: float) -> str:
    """Interpolate two #rrggbb colors; empty fill stays empty."""
    if not from_hex:
        return to_hex
    if not to_hex:
        return from_hex if t < 1.0 else ""
    try:
        fr = int(from_hex[1:3], 16)
        fg = int(from_hex[3:5], 16)
        fb = int(from_hex[5:7], 16)
        tr = int(to_hex[1:3], 16)
        tg = int(to_hex[3:5], 16)
        tb = int(to_hex[5:7], 16)
        r = min(255, max(0, round(fr + (tr - fr) * t)))
        g = min(255, max(0, round(fg + (tg - fg) * t)))
        b = min(255, max(0, round(fb + (tb - fb) * t)))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return to_hex if t >= 1.0 else from_hex


class _TileRenderMixin:
    """_TileRenderMixin (see tile_grid.py)."""

    # Skeleton (shimmer) loading placeholders.
    _SKEL_A = "#e2e2e2"
    _SKEL_B = "#f0f0f0"
    _SKEL_TEXT = "#9a9a9a"
    _LABEL_TEXT = "#1f1f1f"
    _FADE_STEPS = 6
    _FADE_MS = 30

    def show_skeleton(self, count=None):
        """Replace tiles with pulsing grey placeholders until set_items()."""
        if self._closed or not self._canvas_alive():
            return
        self.hide_skeleton()
        old = count or len(self._items) or 12
        count = max(4, min(24, old))
        self._skeleton = True

        tile_w = self._tile_w()
        tile_h = self._tile_h()
        margin = self._margin()
        icon_px = self._icon_px()
        canvas_w = self.canvas.winfo_width() or scale_size(600, self)
        cols = max(1, (canvas_w - margin * 2) // tile_w)
        self._cols = cols

        try:
            self.canvas.delete("all")
        except Exception:
            self._skeleton = False
            return
        self._key_items = {}
        self._item_key = {}
        self._focus_rect = None
        self._hovered = None
        self._skel_items = []

        for idx in range(count):
            row, col = divmod(idx, cols)
            x1 = margin + col * tile_w
            y1 = margin + row * tile_h
            x2 = x1 + tile_w - 6
            y2 = y1 + tile_h - 6
            cx = (x1 + x2) // 2
            icon_y = y1 + scale_size(32, self)
            try:
                bg = self.canvas.create_rectangle(
                    x1, y1, x2, y2, fill=self._SKEL_A, outline="", width=0,
                    tags=("skel",))
                iy1, iy2 = icon_y - icon_px // 2, icon_y + icon_px // 2
                block = self.canvas.create_rectangle(
                    cx - icon_px // 2, iy1, cx + icon_px // 2, iy2,
                    fill=self._SKEL_B, outline="", width=0, tags=("skel",))
                ty = y1 + scale_size(78, self)
                bar_w = tile_w - 28
                bar1 = self.canvas.create_rectangle(
                    cx - bar_w // 2, ty - 5, cx + bar_w // 2, ty + 5,
                    fill=self._SKEL_B, outline="", width=0, tags=("skel",))
                bar2 = self.canvas.create_rectangle(
                    cx - bar_w // 3, ty + 9, cx + bar_w // 3, ty + 16,
                    fill=self._SKEL_B, outline="", width=0, tags=("skel",))
            except Exception:
                continue
            self._skel_items.append((bg, block, bar1, bar2))

        rows = (count + cols - 1) // cols
        try:
            self.canvas.configure(scrollregion=(0, 0, canvas_w, margin * 2 + rows * tile_h + 20))
            self.canvas.config(cursor="watch")
        except Exception:
            pass
        self._empty_label.place_forget()
        self._skel_phase = False
        self._shimmer_tick()

    def hide_skeleton(self):
        """Stop the shimmer; the next set_items()/clear() repaints."""
        self._cancel_fade()
        self._cancel(getattr(self, '_shimmer_after', None))
        self._shimmer_after = None
        if getattr(self, '_skeleton', False):
            self._skeleton = False
            self._skel_items = []
            try:
                self.canvas.config(cursor="")
            except Exception:
                pass

    def _cancel_fade(self):
        self._cancel(getattr(self, '_fade_after', None))
        self._fade_after = None

    def _start_fade(self):
        """Crossfade just-rendered tiles from skeleton grey to final colors.

        Tk canvas items have no opacity, so tile backgrounds and labels are
        interpolated instead; icons (cached photos) appear instantly.
        """
        self._cancel_fade()
        if self._closed or not self._canvas_alive():
            return
        selected = set(self._selected)
        snapshot = []
        try:
            for key, (bg, _icon, txt) in self._key_items.items():
                target = "#cce8ff" if key in selected else ""
                self.canvas.itemconfig(bg, fill=self._SKEL_A)
                self.canvas.itemconfig(txt, fill=self._SKEL_TEXT)
                snapshot.append((bg, target, txt))
        except Exception:
            return
        if not snapshot:
            return
        self._fade_snapshot = snapshot
        self._fade_tick(1)

    def _fade_tick(self, step):
        if self._closed or not self._canvas_alive():
            self._fade_after = None
            return
        snapshot = getattr(self, '_fade_snapshot', None)
        if not snapshot:
            self._fade_after = None
            return
        last = step >= self._FADE_STEPS
        t = 1.0 if last else step / self._FADE_STEPS
        try:
            for bg, target, txt in snapshot:
                self.canvas.itemconfig(bg, fill=_lerp_color(self._SKEL_A, target, t))
                self.canvas.itemconfig(txt, fill=_lerp_color(self._SKEL_TEXT, self._LABEL_TEXT, t))
        except Exception:
            self._fade_after = None
            return
        if last:
            self._fade_after = None
            self._fade_snapshot = None
            self._apply_selection(cancel_fade=False)
            return
        self._cancel(self._fade_after)
        try:
            self._fade_after = self.after(self._FADE_MS, lambda: self._fade_tick(step + 1))
        except Exception:
            self._fade_after = None

    def _shimmer_tick(self):
        if self._closed or not getattr(self, '_skeleton', False):
            return
        if not self._canvas_alive():
            return
        self._skel_phase = not getattr(self, '_skel_phase', False)
        Lo, Hi = (self._SKEL_A, self._SKEL_B) if self._skel_phase else (self._SKEL_B, self._SKEL_A)
        try:
            for bg, block, bar1, bar2 in self._skel_items:
                self.canvas.itemconfig(bg, fill=Lo)
                self.canvas.itemconfig(block, fill=Hi)
                self.canvas.itemconfig(bar1, fill=Hi)
                self.canvas.itemconfig(bar2, fill=Hi)
        except Exception:
            return
        self._cancel(self._shimmer_after)
        try:
            self._shimmer_after = self.after(350, self._shimmer_tick)
        except Exception:
            self._shimmer_after = None

    def _render(self, fade=False):
        if self._closed or not self._canvas_alive():
            return
        self._cancel_fade()
        self._cancel(self._resize_after)
        self._resize_after = None
        try:
            self.canvas.delete("all")
        except Exception:
            return
        self._key_items = {}
        self._item_key = {}
        self._focus_rect = None
        self._hovered = None

        tile_w = self._tile_w()
        tile_h = self._tile_h()
        margin = self._margin()
        icon_off = scale_size(32, self)
        text_off = scale_size(78, self)
        canvas_w = self.canvas.winfo_width() or scale_size(600, self)
        cols = max(1, (canvas_w - margin * 2) // tile_w)
        self._cols = cols

        for idx, (key, label) in enumerate(self._items):
            row, col = divmod(idx, cols)
            x1 = margin + col * tile_w
            y1 = margin + row * tile_h
            x2 = x1 + tile_w - 6
            y2 = y1 + tile_h - 6
            cx = (x1 + x2) // 2
            try:
                bg = self.canvas.create_rectangle(
                    x1, y1, x2, y2, fill="", outline="", width=1, tags=("tile",))
                icon_img = self._icons.get(key, self._default_icon)
                if icon_img is not None:
                    icon = self.canvas.create_image(cx, y1 + icon_off, image=icon_img, tags=("tile",))
                else:
                    icon = self.canvas.create_text(
                        cx, y1 + icon_off, text="◻", font=("Segoe UI", 20),
                        fill="#999999", tags=("tile",))
                text = (label if len(label) <= 18 else label[:16] + "…")
                txt = self.canvas.create_text(
                    cx, y1 + text_off, text=text, font=("Segoe UI", 9),
                    fill="#1f1f1f", width=tile_w - 12, justify=tk.CENTER, tags=("tile",))
            except Exception:
                continue
            self._key_items[key] = (bg, icon, txt)
            self._item_key[bg] = key
            self._item_key[icon] = key
            self._item_key[txt] = key

        rows = (len(self._items) + cols - 1) // cols if self._items else 1
        try:
            self.canvas.configure(scrollregion=(0, 0, canvas_w, margin * 2 + rows * tile_h + 20))
        except Exception:
            pass
        self._apply_selection(cancel_fade=False)
        self._update_empty()
        if fade:
            self._start_fade()
        self._schedule_visible_notify()

    def _relayout(self):
        """Reposition existing items when only the width changed (no recreate)."""
        if self._closed or not self._items or not self._canvas_alive():
            return
        tile_w = self._tile_w()
        tile_h = self._tile_h()
        margin = self._margin()
        icon_off = scale_size(32, self)
        text_off = scale_size(78, self)
        canvas_w = self.canvas.winfo_width()
        if canvas_w <= 1:
            return
        cols = max(1, (canvas_w - margin * 2) // tile_w)
        if cols == self._cols:
            return
        self._cols = cols
        try:
            for idx, (key, _label) in enumerate(self._items):
                trio = self._key_items.get(key)
                if not trio:
                    continue
                row, col = divmod(idx, cols)
                x1 = margin + col * tile_w
                y1 = margin + row * tile_h
                x2 = x1 + tile_w - 6
                y2 = y1 + tile_h - 6
                cx = (x1 + x2) // 2
                self.canvas.coords(trio[0], x1, y1, x2, y2)
                self.canvas.coords(trio[1], cx, y1 + icon_off)
                self.canvas.coords(trio[2], cx, y1 + text_off)
                self.canvas.itemconfig(trio[2], width=tile_w - 12)
            rows = (len(self._items) + cols - 1) // cols
            self.canvas.configure(scrollregion=(0, 0, canvas_w, margin * 2 + rows * tile_h + 20))
        except Exception:
            pass
        self._apply_selection(cancel_fade=False)
        self._schedule_visible_notify()

    def _update_empty(self):
        try:
            if self._items:
                self._empty_label.place_forget()
            else:
                self._empty_label.place(relx=0.5, rely=0.4, anchor='center')
        except Exception:
            pass

    def _apply_selection(self, cancel_fade=True):
        if self._closed or not self._canvas_alive():
            return
        if cancel_fade:
            self._cancel_fade()
        try:
            selected = set(self._selected)
            hovered = self._hovered
            for key, (bg, _icon, _txt) in self._key_items.items():
                if key in selected:
                    self.canvas.itemconfig(bg, fill="#cce8ff", outline="#2684ff")
                elif key == hovered:
                    self.canvas.itemconfig(bg, fill="#e8f0fe", outline="#cce8ff")
                else:
                    self.canvas.itemconfig(bg, fill="", outline="")
            self._draw_focus()
        except Exception:
            pass

    def _draw_focus(self):
        try:
            if self._focus_rect:
                self.canvas.delete(self._focus_rect)
                self._focus_rect = None
            focus = self._focus if self._focus in self._key_items else None
            if focus is None and self._selected:
                focus = self._selected[-1] if self._selected[-1] in self._key_items else None
            if focus is not None:
                trio = self._key_items.get(focus)
                if trio:
                    box = self.canvas.coords(trio[0])
                    if box:
                        self._focus_rect = self.canvas.create_rectangle(
                            *box, outline="#2684ff", width=2, tags=("grid_focus",))
        except Exception:
            pass

