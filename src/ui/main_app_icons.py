"""MainWindow mixin: app icon cache, async extraction, saving."""

import hashlib
import os
import shutil
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List, Optional
from .dpi import scale_size


class _AppIconsMixin:
    """_AppIconsMixin for MainWindow (see main_window.py)."""

    def _get_default_icon_path(self) -> Optional[str]:
        candidates = [
            Path(__file__).resolve().parent / 'assets' / 'android.png',
            Path(__file__).resolve().parent.parent / 'assets' / 'android.png',
            Path(__file__).resolve().parent / 'android.png',
            Path(getattr(sys, '_MEIPASS', '')) / 'assets' / 'android.png',
        ]
        for p in candidates:
            if p.is_file():
                return str(p)
        return None

    def _create_default_app_icon(self) -> tk.PhotoImage:
        size = scale_size(48, self.root)
        default_path = self._get_default_icon_path()
        if default_path:
            try:
                raw_img = tk.PhotoImage(file=default_path)
                w = raw_img.width()
                sub = max(1, round(w / size))
                return raw_img.subsample(sub, sub) if sub > 1 else raw_img
            except Exception:
                pass

        img = tk.PhotoImage(width=size, height=size)
        r = int(size * 0.2)
        green = "#27ae60"
        img.put(green, to=(0, r, size, size - r))
        img.put(green, to=(r, 0, size - r, size))
        for i in range(r):
            dx = int((r * r - (r - i - 0.5) ** 2) ** 0.5)
            img.put(green, to=(r - dx, i, r, i + 1))
            img.put(green, to=(size - r, i, size - r + dx, i + 1))
            img.put(green, to=(r - dx, size - 1 - i, r, size - i))
            img.put(green, to=(size - r, size - 1 - i, size - r + dx, size - i))

        cx, cy = size // 2, int(size * 0.56)
        head_r = int(size * 0.22)
        white = "#ffffff"
        for y in range(cy - head_r, cy):
            dy = cy - y
            if head_r * head_r - dy * dy >= 0:
                hw = int((head_r * head_r - dy * dy) ** 0.5)
                img.put(white, to=(cx - hw, y, cx + hw + 1, y + 1))

        eye_y = int(cy - head_r * 0.45)
        eye_spacing = int(head_r * 0.45)
        eye_sz = max(2, int(size * 0.05))
        img.put(green, to=(cx - eye_spacing - eye_sz // 2, eye_y, cx - eye_spacing + eye_sz // 2 + 1, eye_y + eye_sz))
        img.put(green, to=(cx + eye_spacing - eye_sz // 2, eye_y, cx + eye_spacing + eye_sz // 2 + 1, eye_y + eye_sz))

        ant_len = int(size * 0.1)
        for d in range(ant_len):
            img.put(white, to=(cx - eye_spacing - d, cy - head_r - d, cx - eye_spacing - d + 2, cy - head_r - d + 1))
            img.put(white, to=(cx + eye_spacing + d, cy - head_r - d, cx + eye_spacing + d + 2, cy - head_r - d + 1))

        return img

    def _get_icon_cache_dir(self) -> str:
        try:
            return self.config.get_cache_dir('icons')
        except Exception:
            p = os.path.join(tempfile.gettempdir(), 'droidmgr_icons')
            os.makedirs(p, exist_ok=True)
            return p

    def _save_app_icon(self):
        pkgs = self._get_selected_packages()
        if not pkgs or not self._require_device():
            return

        cache_dir = self._get_icon_cache_dir()
        dev_id = self.selected_device
        device_key = hashlib.sha256(dev_id.encode('utf-8')).hexdigest()[:10]

        pkg_paths = {}
        for app in getattr(self, '_apps_data', []):
            if app.get('package') and app.get('path'):
                pkg_paths[app['package']] = app['path']

        def get_or_extract_icon(pkg):
            # 1. Check existing cached icon
            try:
                for fname in os.listdir(cache_dir):
                    if fname.startswith(f"{pkg}_{device_key}_") and fname.endswith("_icon.png"):
                        full_p = os.path.join(cache_dir, fname)
                        if os.path.isfile(full_p) and os.path.getsize(full_p) > 0:
                            return full_p
            except Exception:
                pass

            # 2. Extract icon using adb
            try:
                apk_p = pkg_paths.get(pkg)
                p = self.device_manager.adb.extract_app_icon(dev_id, pkg, cache_dir, known_apk_path=apk_p)
                if p and os.path.isfile(p) and os.path.getsize(p) > 0:
                    return p
            except Exception:
                pass
            return None

        if len(pkgs) == 1:
            pkg = pkgs[0]
            self._set_status(f"Fetching app icon for {pkg}...")
            icon_path = get_or_extract_icon(pkg) or self._get_default_icon_path()
            if not icon_path:
                self._show_warning(f"Could not extract icon for '{pkg}'.")
                self._set_status(f"Could not extract icon for {pkg}")
                return

            dest = filedialog.asksaveasfilename(
                parent=self.root,
                title="Save App Icon",
                defaultextension=".png",
                initialfile=f"{pkg}_icon.png",
                filetypes=[("PNG Image", "*.png"), ("All Files", "*.*")]
            )
            if dest:
                try:
                    shutil.copy2(icon_path, dest)
                    self._set_status(f"App icon saved to {dest}")
                    messagebox.showinfo("Save App Icon", f"App icon saved to:\n{dest}", parent=self.root)
                except Exception as exc:
                    self._show_error("Save Icon Error", f"Failed to save icon:\n{exc}")
        else:
            dest_dir = filedialog.askdirectory(
                parent=self.root,
                title=f"Select Directory to Save {len(pkgs)} App Icons"
            )
            if not dest_dir:
                return

            saved = 0
            default_path = self._get_default_icon_path()
            self._set_status(f"Saving {len(pkgs)} app icons...")
            for pkg in pkgs:
                ip = get_or_extract_icon(pkg) or default_path
                if ip:
                    try:
                        shutil.copy2(ip, os.path.join(dest_dir, f"{pkg}_icon.png"))
                        saved += 1
                    except Exception:
                        pass
            self._set_status(f"Saved {saved} of {len(pkgs)} app icons to {dest_dir}")
            messagebox.showinfo("Save App Icons", f"Saved {saved} of {len(pkgs)} app icons to:\n{dest_dir}", parent=self.root)

    def _load_app_icons_async(self, packages):
        if not self.selected_device or not packages:
            return
        manager = getattr(self, 'device_manager', None)
        if not manager or not hasattr(manager, 'adb'):
            return

        to_fetch = [p for p in packages
                    if p not in self._app_icon_cache and p not in self._app_icon_loading]
        if not to_fetch:
            return

        if not hasattr(self, '_icon_pending_packages'):
            self._icon_pending_packages = []
        if not hasattr(self, '_icon_lock'):
            self._icon_lock = threading.Lock()

        with self._icon_lock:
            for p in to_fetch:
                if p not in self._icon_pending_packages:
                    self._icon_pending_packages.append(p)
            self._app_icon_loading.update(to_fetch)

        if not getattr(self, '_icon_worker_active', False):
            self._icon_worker_active = True
            threading.Thread(target=self._icon_loader_worker, daemon=True).start()

    def _icon_loader_worker(self):
        dev_id = self.selected_device
        current_gen = getattr(self, '_icon_extract_generation', 0)
        cache_dir = self._get_icon_cache_dir()
        manager = getattr(self, 'device_manager', None)
        if not manager or not hasattr(manager, 'adb'):
            with self._icon_lock:
                self._icon_worker_active = False
            return

        def is_cancelled():
            return (
                getattr(self, '_closing', False)
                or current_gen != getattr(self, '_icon_extract_generation', 0)
                or self.selected_device != dev_id
            )

        try:
            while not is_cancelled():
                pkg_paths = {}
                for app in getattr(self, '_apps_data', []):
                    if app.get('package') and app.get('path'):
                        pkg_paths[app['package']] = app['path']

                chunk = []
                with self._icon_lock:
                    if not self._icon_pending_packages:
                        break
                    visible = set(self._visible_grid_packages()) if hasattr(self, '_visible_grid_packages') else set()
                    vis_chunk = [p for p in self._icon_pending_packages if p in visible]
                    if vis_chunk:
                        chunk = vis_chunk[:40]
                    else:
                        chunk = self._icon_pending_packages[:40]
                    for p in chunk:
                        self._icon_pending_packages.remove(p)

                if not chunk or is_cancelled():
                    break

                batch_extracted = {}
                if hasattr(manager.adb, 'extract_app_icons_batch'):
                    try:
                        batch_extracted = manager.adb.extract_app_icons_batch(
                            dev_id, chunk, cache_dir, cancel_check=is_cancelled
                        )
                    except Exception:
                        batch_extracted = {}

                for pkg, icon_path in batch_extracted.items():
                    if is_cancelled():
                        return
                    def apply_icon(p=pkg, ip=icon_path):
                        if is_cancelled():
                            return
                        try:
                            raw_img = tk.PhotoImage(file=ip)
                            w = raw_img.width()
                            target_sz = scale_size(48, self.root)
                            sub = max(1, round(w / target_sz))
                            scaled = raw_img.subsample(sub, sub) if sub > 1 else raw_img
                            self._app_icon_cache[p] = scaled
                            if hasattr(self, 'app_grid'):
                                self.app_grid.update_icon(p, scaled)
                        except Exception:
                            pass
                        finally:
                            self._app_icon_loading.discard(p)
                    self.root.after(0, apply_icon)

                remaining = [p for p in chunk if p not in batch_extracted]
                for pkg in remaining:
                    if is_cancelled():
                        return
                    apk_path = pkg_paths.get(pkg)
                    try:
                        icon_path = manager.adb.extract_app_icon(
                            dev_id, pkg, cache_dir, known_apk_path=apk_path
                        )
                        if is_cancelled():
                            return
                        if icon_path and os.path.isfile(icon_path):
                            def apply_single(p=pkg, ip=icon_path):
                                if is_cancelled():
                                    return
                                try:
                                    raw_img = tk.PhotoImage(file=ip)
                                    w = raw_img.width()
                                    target_sz = scale_size(48, self.root)
                                    sub = max(1, round(w / target_sz))
                                    scaled = raw_img.subsample(sub, sub) if sub > 1 else raw_img
                                    self._app_icon_cache[p] = scaled
                                    if hasattr(self, 'app_grid'):
                                        self.app_grid.update_icon(p, scaled)
                                except Exception:
                                    pass
                                finally:
                                    self._app_icon_loading.discard(p)
                            self.root.after(0, apply_single)
                        else:
                            self.root.after(0, lambda p=pkg: (
                                self._app_icon_cache.setdefault(p, self._default_app_icon),
                                self._app_icon_loading.discard(p)
                            ))
                    except Exception:
                        self.root.after(0, lambda p=pkg: (
                            self._app_icon_cache.setdefault(p, self._default_app_icon),
                            self._app_icon_loading.discard(p)
                        ))
        finally:
            with self._icon_lock:
                self._icon_worker_active = False
                if self._icon_pending_packages and not is_cancelled():
                    self._icon_worker_active = True
                    threading.Thread(target=self._icon_loader_worker, daemon=True).start()

