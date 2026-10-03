"""TileGrid mixin: pointer, wheel, keyboard and resize handling."""


class _TileInputMixin:
    """_TileInputMixin (see tile_grid.py)."""

    def _key_at(self, x: int, y: int) -> Optional[str]:
        try:
            cx = self.canvas.canvasx(x)
            cy = self.canvas.canvasy(y)
            for item in reversed(self.canvas.find_overlapping(cx, cy, cx, cy)):
                if item == self._focus_rect:
                    continue
                key = self._item_key.get(item)
                if key is not None:
                    return key
        except Exception:
            pass
        return None

    def _selected_set(self):
        return set(self._selected)

    def _order(self, keys):
        """Keys in grid order."""
        pos = {k: i for i, k in enumerate(self._keys)}
        return sorted(keys, key=lambda k: pos.get(k, len(pos)))

    def _pick(self, key: Optional[str], mode: str = "single"):
        if getattr(self, '_skeleton', False):
            return
        if key is None or key not in self._keys:
            if mode == "single":
                self._selected = []
                self._anchor = None
                self._focus = None
            else:
                return
        elif mode == "toggle":
            sel = self._selected_set()
            if key in sel:
                sel.discard(key)
            else:
                sel.add(key)
            self._selected = self._order(sel)
            self._focus = key
            if self._anchor not in self._keys:
                self._anchor = key
        elif mode == "range":
            if self._anchor not in self._keys:
                self._anchor = self._focus if self._focus in self._keys else key
            anchor = self._anchor
            try:
                lo = self._keys.index(anchor)
                hi = self._keys.index(key)
            except ValueError:
                lo = hi = self._keys.index(key)
            if lo > hi:
                lo, hi = hi, lo
            self._selected = self._keys[lo:hi + 1]
            self._focus = key
        else:
            self._selected = [key]
            self._anchor = key
            self._focus = key
        self._hovered = None
        self._apply_selection()
        self._notify_select()

    def _notify_select(self):
        if self._on_select:
            try:
                self._on_select(self.get_selected())
            except Exception:
                pass

    def _fire_activate(self):
        if getattr(self, '_skeleton', False):
            return "break"
        if self._on_activate:
            try:
                self._on_activate(self.get_focused())
            except Exception:
                pass
        return "break"

    def _on_configure(self, event):
        self._cancel(self._resize_after)
        self._resize_after = self.after(80, self._relayout_delayed)

    def _relayout_delayed(self):
        self._resize_after = None
        if self._closed or not self._canvas_alive():
            return
        try:
            if self.canvas.winfo_width() <= 1:
                return
        except Exception:
            return
        self._relayout()

    def _on_scrollbar(self, *args):
        try:
            self.canvas.yview(*args)
        except Exception:
            return
        self._schedule_visible_notify()

    def _on_wheel(self, event):
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            return
        self._schedule_visible_notify()
        return "break"

    def _on_wheel_up(self, _event):
        try:
            self.canvas.yview_scroll(-1, "units")
        except Exception:
            pass
        self._schedule_visible_notify()
        return "break"

    def _on_wheel_down(self, _event):
        try:
            self.canvas.yview_scroll(1, "units")
        except Exception:
            pass
        self._schedule_visible_notify()
        return "break"

    def _schedule_visible_notify(self):
        if not self._on_visible:
            return
        self._cancel(self._visible_after)
        try:
            self._visible_after = self.after(60, self._fire_visible)
        except Exception:
            pass

    def _fire_visible(self):
        self._visible_after = None
        if self._closed or not self._on_visible:
            return
        try:
            self._on_visible(self.get_visible_keys())
        except Exception:
            pass

    def _on_motion(self, event):
        if getattr(self, '_skeleton', False):
            return
        key = self._key_at(event.x, event.y)
        if key == self._hovered:
            return
        self._hovered = key
        self._apply_selection()
        try:
            self.canvas.config(cursor="hand2" if key else "")
        except Exception:
            pass

    def _on_leave(self, _event):
        if self._hovered is None:
            return
        self._hovered = None
        self._apply_selection()
        try:
            self.canvas.config(cursor="")
        except Exception:
            pass

    def _on_right_click(self, event):
        key = self._key_at(event.x, event.y)
        if self._on_context:
            try:
                self._on_context(event, key)
            except Exception:
                pass

    @staticmethod
    def _mods(event) -> tuple:
        """(shift, ctrl) from a button/key event state mask."""
        try:
            state = event.state
        except Exception:
            return False, False
        return bool(state & 0x0001), bool(state & 0x0004)

    def _on_press(self, event):
        if getattr(self, '_skeleton', False):
            return
        try:
            self.canvas.focus_set()
        except Exception:
            pass
        try:
            cx = self.canvas.canvasx(event.x)
            cy = self.canvas.canvasy(event.y)
        except Exception:
            return
        self._press_xy = (cx, cy)
        self._band_start = (cx, cy)
        self._press_key = self._key_at(event.x, event.y)
        self._band_active = False

    def _on_drag_motion(self, event):
        if getattr(self, '_skeleton', False) or self._press_xy is None:
            return
        try:
            cx = self.canvas.canvasx(event.x)
            cy = self.canvas.canvasy(event.y)
        except Exception:
            return
        x0, y0 = self._press_xy
        if not self._band_active:
            if max(abs(cx - x0), abs(cy - y0)) < 5:
                return
            self._band_active = True
            try:
                self._band_rect = self.canvas.create_rectangle(
                    x0, y0, x0, y0, outline="#2684ff", width=1,
                    dash=(4, 2), tags=("band",))
                self.canvas.tag_raise(self._band_rect)
            except Exception:
                self._band_rect = None
        if self._band_rect is not None:
            try:
                self.canvas.coords(self._band_rect, x0, y0, cx, cy)
            except Exception:
                pass

    def _on_release(self, event):
        if getattr(self, '_skeleton', False):
            self._press_xy = None
            return
        was_band = self._band_active
        press_key = self._press_key
        self._discard_band()
        self._press_xy = None
        if was_band:
            self._commit_band_from_event(event)
            return "break"
        shift, ctrl = self._mods(event)
        key = press_key if press_key is not None else self._key_at(event.x, event.y)
        if key is None:
            if not shift and not ctrl:
                self._pick(None, "single")
        elif ctrl:
            self._pick(key, "toggle")
        elif shift:
            self._pick(key, "range")
        else:
            self._pick(key, "single")
        return "break"

    def _on_tile_double(self, event):
        if getattr(self, '_skeleton', False):
            return "break"
        key = self._key_at(event.x, event.y)
        if key is not None:
            self._pick(key, "single")
            self._fire_activate()
        return "break"

    def _commit_band_from_event(self, event):
        try:
            cx = self.canvas.canvasx(event.x)
            cy = self.canvas.canvasy(event.y)
        except Exception:
            return
        x0, y0 = self._band_start
        x1, x2 = (x0, cx) if x0 <= cx else (cx, x0)
        y1, y2 = (y0, cy) if y0 <= cy else (cy, y0)
        try:
            hits = self.canvas.find_enclosed(x1, y1, x2, y2)
        except Exception:
            return
        boxed = [self._item_key[i] for i in hits if i in self._item_key]
        if not boxed:
            shift, ctrl = self._mods(event)
            if not shift and not ctrl:
                self._pick(None, "single")
            return
        self._commit_band(boxed, event)

    def _commit_band(self, boxed, event):
        """Merge rubber-band hits by modifier: replace / add / toggle."""
        ordered = self._order(set(boxed))
        if not ordered:
            return
        shift, ctrl = self._mods(event)
        if ctrl:
            sel = self._selected_set()
            for k in ordered:
                if k in sel:
                    sel.discard(k)
                else:
                    sel.add(k)
            self._selected = self._order(sel)
        elif shift:
            sel = self._selected_set() | set(ordered)
            self._selected = self._order(sel)
        else:
            self._selected = ordered
        self._anchor = ordered[-1]
        self._focus = ordered[-1]
        self._hovered = None
        self._apply_selection()
        self._notify_select()

    def _discard_band(self):
        self._band_active = False
        if self._band_rect is not None:
            try:
                self.canvas.delete(self._band_rect)
            except Exception:
                pass
            self._band_rect = None

    def _cancel_band(self, event=None):
        self._discard_band()
        self._press_xy = None
        return "break"

    def _focus_index(self):
        focus = self.get_focused()
        if focus in self._keys:
            return self._keys.index(focus)
        return 0 if self._keys else -1

    def _move(self, dx: int, dy: int, extend: bool = False):
        if getattr(self, '_skeleton', False):
            return "break"
        if not self._keys:
            return "break"
        idx = self._focus_index()
        if idx < 0:
            return "break"
        cols = max(1, self._cols)
        row, col = divmod(idx, cols)
        last_row = (len(self._keys) - 1) // cols
        row = max(0, min(last_row, row + dy))
        col = max(0, min(cols - 1, col + dx))
        target = min(len(self._keys) - 1, row * cols + col)
        key = self._keys[target]
        if extend:
            if self._anchor not in self._keys:
                self._anchor = self._focus if self._focus in self._keys else self._keys[idx]
            self._pick(key, "range")
        else:
            self._pick(key, "single")
        self.scroll_to_key(key)
        self._schedule_visible_notify()
        return "break"

    def _go_to(self, index: int, extend: bool = False):
        if getattr(self, '_skeleton', False):
            return "break"
        if not self._keys:
            return "break"
        key = self._keys[index]
        if extend:
            if self._anchor not in self._keys:
                anchor_idx = self._focus_index()
                self._anchor = self._keys[anchor_idx] if anchor_idx >= 0 else key
            self._pick(key, "range")
        else:
            self._pick(key, "single")
        self.scroll_to_key(key)
        self._schedule_visible_notify()
        return "break"

    def _move_page(self, direction: int, extend: bool = False):
        try:
            height = self.canvas.winfo_height() or self._tile_h()
            rows = max(1, height // self._tile_h())
        except Exception:
            rows = 1
        return self._move(0, direction * rows, extend=extend)

    def _on_destroy(self, _event):
        self._closed = True
        self.hide_skeleton()
        self._cancel(self._resize_after)
        self._cancel(self._visible_after)
        self._resize_after = self._visible_after = None

