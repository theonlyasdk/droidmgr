"""FileManager mixin: directory listing, cache and refresh."""

import copy
import threading
import tkinter as tk
from tkinter import messagebox
from core import ADBDeviceOfflineError, ADBDeviceNotFoundError

# Listing cache size: back/forward navigation and tab switches re-list the
# same directories, and each list costs an adb round trip.
_LISTING_CACHE_SIZE = 32


class _FileListingMixin:
    """_FileListingMixin (see file_manager.py)."""

    def _clear_list(self):
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        self.files_data.clear()
        self.files_by_name.clear()
        self.current_files = []
        self._empty_key = None
        self._empty_names = frozenset()
        if hasattr(self, 'file_grid'):
            self.file_grid.clear()

    def _get_cached_listing(self, key):
        """Return a private copy of a cached listing, or None on a miss."""
        try:
            entry = self._listing_cache.pop(key)
        except KeyError:
            return None
        # MRU: re-insert so eviction drops the least recently used.
        self._listing_cache[key] = entry
        files, writable = entry
        return copy.deepcopy(files), writable

    def _store_cached_listing(self, key, files, writable):
        self._listing_cache[key] = (copy.deepcopy(files), writable)
        while len(self._listing_cache) > _LISTING_CACHE_SIZE:
            self._listing_cache.popitem(last=False)

    def invalidate_cache(self):
        """Drop cached listings after anything that mutates the device."""
        self._listing_cache.clear()

    def _set_loading(self, loading):
        """Lock/unlock navigation, path bar and action buttons during loads.

        The Refresh button stays enabled as the escape hatch; everything
        else would act on a listing that is about to be replaced.
        """
        self._loading = loading
        if loading:
            self.up_btn.config(state=tk.DISABLED)
            self.go_btn.config(state=tk.DISABLED)
            self.path_entry.config(state='readonly')
            self._set_status(f"Loading {self.current_path}...")
        else:
            self.go_btn.config(state=tk.NORMAL)
            self.path_entry.config(state=tk.NORMAL)
        self._update_navigation_buttons()
        self._update_selection_buttons()

    def _finish_loading(self):
        """Hide a pending/visible skeleton and unlock the controls."""
        timer, self._skeleton_after = self._skeleton_after, None
        if timer is not None:
            try:
                self.frame.after_cancel(timer)
            except Exception:
                pass
        try:
            if hasattr(self, 'file_grid'):
                self.file_grid.hide_skeleton()
        except Exception:
            pass
        if getattr(self, '_loading', False):
            self._set_loading(False)

    def _maybe_show_skeleton(self, seq):
        try:
            if (seq != self._refresh_seq or not getattr(self, '_loading', False)
                    or not self.frame.winfo_exists()):
                return
            if not self.config.get('file_manager', 'grid_animations', True):
                return
            if self.view_mode_var.get() == "grid" and hasattr(self, 'file_grid'):
                self.file_grid.show_skeleton()
        except Exception:
            pass

    def refresh(self):
        if not self.selected_device:
            return

        self._refresh_seq += 1
        seq = self._refresh_seq
        self._set_loading(True)
        # Delayed skeleton: instant (cached) loads never flash it.
        try:
            delay = self.config.get('file_manager', 'skeleton_delay_ms', 150)
            delay = max(0, min(1000, int(delay)))
        except (TypeError, ValueError):
            delay = 150
        try:
            if self._skeleton_after is not None:
                self.frame.after_cancel(self._skeleton_after)
        except Exception:
            pass
        try:
            self._skeleton_after = self.frame.after(
                delay, lambda: self._maybe_show_skeleton(seq))
        except Exception:
            self._skeleton_after = None

        # Avoid running commands if the device is known to be offline or unauthorized
        if hasattr(self.device_manager, 'is_device_ready'):
            try:
                if not self.device_manager.is_device_ready(self.selected_device):
                    status = None
                    if hasattr(self.device_manager, 'get_device_status'):
                        status = self.device_manager.get_device_status(self.selected_device)
                    status_str = status.lower() if status else 'offline'
                    if status_str == 'unauthorized':
                        tag_text = "[Unauthorized]"
                        desc_text = "Device is unauthorized. Please accept the USB debugging prompt on your phone screen."
                    else:
                        tag_text = "[Offline]"
                        desc_text = "Device is offline. Reconnect USB cable or restart ADB."

                    def show_offline():
                        if seq != self._refresh_seq:
                            return
                        self._finish_loading()
                        self._clear_list()
                        self.file_grid.set_empty_text(desc_text)
                        self.file_tree.insert(
                            '', tk.END, text=tag_text,
                            values=(desc_text, "", "")
                        )
                        self._set_status(f"Device '{self.selected_device}' is {status_str}.")
                        self._update_navigation_buttons()
                        self._update_selection_buttons()
                    self.frame.after(0, show_offline)
                    return
            except Exception:
                pass

        query_path = self.current_path
        if not query_path.endswith('/'):
            query_path += '/'

        selected_names = set()
        for item_id in self.file_tree.selection():
            vals = self.file_tree.item(item_id, 'values')
            if vals:
                selected_names.add(vals[0])
        yview = self.file_tree.yview()
        # Read on the UI thread: Tk variables are not safe to touch from workers.
        want_grid = self.view_mode_var.get() == "grid"
        device_id = self.selected_device
        show_hidden_cfg = self.config.get('file_manager', 'show_hidden', False)
        use_exact_cfg = self.config.get('file_manager', 'use_exact_sizes', False)

        def task():
            try:
                path = query_path

                cache_key = (device_id, path, show_hidden_cfg, use_exact_cfg)
                cached = self._get_cached_listing(cache_key)
                if cached is not None:
                    files, is_writable = cached
                else:
                    # One round trip for listing + writability (was two).
                    files, is_writable = self.device_manager.list_dir(
                        device_id, path, show_hidden_cfg, use_exact_cfg)
                    self._store_cached_listing(cache_key, files, is_writable)

                # One batched round trip for the whole directory, grid only.
                empty_names = frozenset()
                if want_grid and any(f['is_dir'] for f in files):
                    try:
                        empty_names = frozenset(self.device_manager.get_empty_dirs(device_id, path))
                    except Exception:
                        empty_names = frozenset()

                def update():
                    if seq != self._refresh_seq:
                        return
                    self._finish_loading()
                    self.is_current_path_writable = is_writable
                    is_same_dir = (path == getattr(self, '_last_rendered_path', None))
                    # Clear the list inside the main thread just before inserting to avoid duplicates and concurrency bugs
                    self._clear_list()
                    self.current_files = list(files)
                    if want_grid:
                        self._empty_key = (device_id, path)
                        self._empty_names = empty_names
                    restored_ids = []
                    for f in files:
                        icon = "[DIR]" if f['is_dir'] else "[FILE]"
                        item_id = self.file_tree.insert('', tk.END, text=icon,
                                            values=(f['name'], f['size'], f['permissions']),
                                            tags=('directory' if f['is_dir'] else 'file',))
                        self.files_data[item_id] = f
                        self.files_by_name[f['name']] = f
                        if f['is_dir']:
                            f['is_empty'] = f['name'] in empty_names
                        if is_same_dir and f['name'] in selected_names:
                            restored_ids.append(item_id)

                    if restored_ids:
                        self.file_tree.selection_set(restored_ids)
                        self.file_tree.focus(restored_ids[0])

                    if is_same_dir and yview:
                        self.file_tree.yview_moveto(yview[0])

                    self.file_grid.set_empty_text("This folder is empty")
                    if self.view_mode_var.get() == "grid":
                        self._render_file_grid()

                    self._last_rendered_path = path
                    self._set_status(f"Browsing {self.current_path}")
                    self._update_navigation_buttons()
                    self._update_selection_buttons()
                self.frame.after(0, update)

            except (ADBDeviceOfflineError, ADBDeviceNotFoundError) as e:
                msg = str(e)
                def handle_offline():
                    if seq != self._refresh_seq:
                        return
                    self._finish_loading()
                    self._clear_list()
                    tag_text = "[Unauthorized]" if "unauthorized" in msg.lower() else "[Offline]"
                    desc_text = "Device is unauthorized. Please accept the USB debugging prompt on your phone screen." if "unauthorized" in msg.lower() else "Device is offline. Reconnect USB cable or restart ADB."
                    self.file_grid.set_empty_text(desc_text)
                    self.file_tree.insert(
                        '', tk.END, text=tag_text,
                        values=(desc_text, "", "")
                    )
                    self._set_status(f"Device '{self.selected_device}' is offline or disconnected.")
                    self._update_navigation_buttons()
                    self._update_selection_buttons()
                self.frame.after(0, handle_offline)
            except Exception as e:
                msg = str(e)
                lower_msg = msg.lower()
                is_offline = any(keyword in lower_msg for keyword in [
                    'device offline', 'offline or unauthorized', 'device not found',
                    'no devices/emulators found', 'disconnected', 'closed', 'unauthorized'
                ])
                if is_offline:
                    def handle_offline():
                        if seq != self._refresh_seq:
                            return
                        self._finish_loading()
                        self._clear_list()
                        tag_text = "[Unauthorized]" if "unauthorized" in lower_msg else "[Offline]"
                        desc_text = "Device is unauthorized. Please accept the USB debugging prompt on your phone screen." if "unauthorized" in lower_msg else "Device is offline. Reconnect USB cable or restart ADB."
                        self.file_grid.set_empty_text(desc_text)
                        self.file_tree.insert(
                            '', tk.END, text=tag_text,
                            values=(desc_text, "", "")
                        )
                        self._set_status(f"Device '{self.selected_device}' is offline or disconnected.")
                        self._update_navigation_buttons()
                        self._update_selection_buttons()
                    self.frame.after(0, handle_offline)
                elif "Permission denied" in msg:
                    # Bounce back to the pre-navigation path exactly once, then
                    # report. The prev != current check stops a denied fallback
                    # from re-triggering itself in a refresh loop.
                    def go_back():
                        if seq != self._refresh_seq:
                            return
                        self._finish_loading()
                        prev = getattr(self, 'previous_path', None)
                        if prev and prev != self.current_path:
                            self.current_path = prev
                            self.path_var.set(self.current_path)
                            self.refresh()
                        if self._permission_dialog_open:
                            self._set_status(f"Permission denied: {path}")
                            return
                        self._permission_dialog_open = True
                        try:
                            messagebox.showerror("Permission Error", self._permission_error_text(path))
                        finally:
                            self._permission_dialog_open = False
                    self.frame.after(0, go_back)
                else:
                    def show_refresh_error():
                        if seq != self._refresh_seq:
                            return
                        self._finish_loading()
                        self._show_error("File Refresh Error", msg)
                    self.frame.after(0, show_refresh_error)
        
        threading.Thread(target=task, daemon=True).start()

    def _permission_error_text(self, path):
        """Permission-denied message, qualified with the recorded root state."""
        text = (f"You do not have permission to access:\n{path}\n\n"
                "Root access might be required.")
        registry = getattr(getattr(self, 'device_manager', None), 'registry', None)
        rooted = registry.is_rooted(self.selected_device) if registry is not None else None
        if rooted is False:
            text += ("\n\nThis device is recorded as not rooted (adb runs without "
                     "root and no su binary was found), so protected system "
                     "directories will stay inaccessible.")
        elif rooted is True:
            adb_root = registry.is_adb_root(self.selected_device)
            if not adb_root:
                text += ("\n\nThis device is recorded as rooted, but adb itself runs "
                         "without root, so access may still need approval on the "
                         "device screen.")
        return text

