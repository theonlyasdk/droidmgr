"""APK static inspection and app-icon loading for the app info dialog."""
"""Split from app_info_dialog.py (MOVE-ONLY); AppInfoDialog mixes this in."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import sys
import shutil
import tempfile


class AppInspectionMixin:
    """APK inspection and icon loading."""

    def _browse_and_inspect_local_apk(self):
        file_path = filedialog.askopenfilename(
            parent=self,
            title="Select Local APK File to Inspect",
            filetypes=[("Android Packages", "*.apk"), ("All Files", "*.*")]
        )
        if file_path:
            self._current_apk_path = file_path
            self._run_inspection_on_file(file_path)

    def _inspect_current_apk(self):
        if self._current_apk_path and os.path.isfile(self._current_apk_path):
            self._run_inspection_on_file(self._current_apk_path)
        else:
            self._load_static_apk_async()

    def _load_static_apk_async(self):
        pkg = self.app_info.get('package')
        if not self.device_id or not pkg or not self.device_manager:
            self.static_status_lbl.config(text="No device link or package available.")
            return

        self.static_status_lbl.config(text="Locating APK on device...")
        def bg_task():
            try:
                # 1. Resolve exact remote APK path via pm path
                remote_apk = None
                try:
                    pm_out = self.device_manager.adb._run_command(['shell', 'pm', 'path', pkg], self.device_id, timeout=8)
                    for line in pm_out.splitlines():
                        line = line.strip()
                        if line.startswith('package:'):
                            remote_apk = line[8:].strip()
                            break
                except Exception:
                    pass

                # Fallback if pm path failed
                if not remote_apk:
                    raw_path = (self.app_info.get('path') or '').strip()
                    if raw_path.startswith('package:'):
                        raw_path = raw_path[8:].strip()
                    if raw_path.endswith('.apk'):
                        remote_apk = raw_path
                    elif raw_path:
                        remote_apk = raw_path.rstrip('/') + '/base.apk'

                if not remote_apk:
                    def no_path():
                        self.static_status_lbl.config(text="Could not resolve APK path on device.")
                    self.after(0, no_path)
                    return

                cache_dir = os.path.join(tempfile.gettempdir(), 'droidmgr_apk_inspect')
                os.makedirs(cache_dir, exist_ok=True)
                local_apk = os.path.join(cache_dir, f"{pkg}_base.apk")

                if not os.path.isfile(local_apk) or os.path.getsize(local_apk) == 0:
                    def pulling_msg():
                        self.static_status_lbl.config(text=f"Pulling {os.path.basename(remote_apk)} from device...")
                    self.after(0, pulling_msg)
                    self.device_manager.adb._run_command(['pull', remote_apk, local_apk], self.device_id, timeout=40)

                if not os.path.isfile(local_apk) or os.path.getsize(local_apk) == 0:
                    def err_pull():
                        self.static_status_lbl.config(text=f"Failed to pull APK from: {remote_apk}")
                    self.after(0, err_pull)
                    return

                self._current_apk_path = local_apk
                self._run_inspection_on_file(local_apk)
            except Exception as e:
                def err():
                    self.static_status_lbl.config(text=f"Inspection error: {e}")
                self.after(0, err)

        threading.Thread(target=bg_task, daemon=True).start()

    def _run_inspection_on_file(self, apk_path):
        from core.apk_icon import inspect_apk
        self.static_status_lbl.config(text=f"Parsing {os.path.basename(apk_path)} statically...")
        def bg():
            try:
                res = inspect_apk(apk_path)
                self.after(0, lambda: self._apply_static_results(res))
            except Exception as ex:
                self.after(0, lambda: self.static_status_lbl.config(text=f"Inspection failed: {ex}"))
        threading.Thread(target=bg, daemon=True).start()

    def _apply_static_results(self, res):
        self._static_data = res
        if res.get('file_size', 0) == 0:
            self.static_status_lbl.config(text=f"Inspection failed: Empty or inaccessible file ({res.get('file_name', '')})")
            return

        self.static_status_lbl.config(text=f"Inspected: {res.get('file_name')} ({res.get('file_size', 0) // 1024} KB)")

        min_s = res.get('min_sdk') or '?'
        tgt_s = res.get('target_sdk') or '?'
        cmp_s = res.get('compile_sdk') or '?'
        self.sdk_lbl.config(text=f"Min: {min_s} | Target: {tgt_s} | Compile: {cmp_s}")

        is_debug = res.get('debuggable', False)
        if is_debug:
            self.debug_lbl.config(text="YES (Debuggable)", foreground="#c00000")
        else:
            self.debug_lbl.config(text="NO (Release)", foreground="#008000")

        schemes = res.get('schemes') or []
        self.sig_schemes_lbl.config(text=", ".join(schemes) if schemes else "None detected")

        dex_count = res.get('dex_count', 0)
        size_kb = res.get('file_size', 0) // 1024
        self.size_dex_lbl.config(text=f"{size_kb:,} KB across {dex_count} DEX file(s)")

        certs = res.get('certificates') or []
        if certs:
            c0 = certs[0]
            self.sha256_entry.delete(0, tk.END)
            self.sha256_entry.insert(0, c0.get('sha256', ''))
            self.subject_lbl.config(text=c0.get('subject', 'Unknown'))
        else:
            self.sha256_entry.delete(0, tk.END)
            self.subject_lbl.config(text="No certificate found")

        # Populate components
        perms = res.get('permissions', [])
        self._perm_all = sorted(perms)
        self._filter_component_list('perm')
        self.comp_notebook.tab(self.perm_tab, text=f"Permissions ({len(perms)})")

        acts = res.get('activities', [])
        self._act_all = sorted(acts)
        self._filter_component_list('act')
        self.comp_notebook.tab(self.act_tab, text=f"Activities ({len(acts)})")

        srvs = res.get('services', [])
        self._srv_all = sorted(srvs)
        self._filter_component_list('srv')
        self.comp_notebook.tab(self.srv_tab, text=f"Services ({len(srvs)})")

        recs = res.get('receivers', [])
        provs = res.get('providers', [])
        rec_prov = [f"[Receiver] {r}" for r in sorted(recs)] + [f"[Provider] {p}" for p in sorted(provs)]
        self._rec_all = rec_prov
        self._filter_component_list('rec')
        self.comp_notebook.tab(self.rec_tab, text=f"Receivers & Providers ({len(rec_prov)})")

    def _get_default_icon_path(self):
        candidates = [
            os.path.join(os.path.dirname(__file__), 'assets', 'android.png'),
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'android.png'),
            os.path.join(os.path.dirname(__file__), 'android.png'),
            os.path.join(getattr(sys, '_MEIPASS', ''), 'assets', 'android.png'),
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return c
        return None

    def _load_icon_async(self):
        try:
            package = self.app_info['package']
            apk_path = self.app_info.get('path')
            try:
                from core.config_manager import ConfigManager
                cache_dir = ConfigManager().get_cache_dir('icons')
            except Exception:
                cache_dir = os.path.join(tempfile.gettempdir(), 'droidmgr_icons')
            icon_path = self.device_manager.adb.extract_app_icon(
                self.device_id, package, cache_dir, known_apk_path=apk_path
            )

            if icon_path and os.path.exists(icon_path):
                self.after(0, lambda p=icon_path: self._update_icon_ui(p))
            else:
                default_icon = self._get_default_icon_path()
                if default_icon:
                    self.after(0, lambda p=default_icon: self._update_icon_ui(p))
                else:
                    self.after(0, lambda: self._set_icon_text_safe("No Icon Found"))
        except Exception:
            default_icon = self._get_default_icon_path()
            if default_icon:
                self.after(0, lambda p=default_icon: self._update_icon_ui(p))
            else:
                self.after(0, lambda: self._set_icon_text_safe("Failed to load"))

    def _set_icon_text_safe(self, text):
        try:
            if not self.winfo_exists():
                return
            if not self.icon_label.winfo_exists():
                return
            self.icon_label.config(text=text)
        except tk.TclError:
            pass

    def _update_icon_ui(self, icon_path):
        try:
            if not self.winfo_exists():
                return
            if not self.icon_label.winfo_exists():
                return
            self.icon_path = icon_path
            self.icon_image = tk.PhotoImage(file=icon_path)
            w = self.icon_image.width()
            h = self.icon_image.height()
            
            # Zoom or subsample to fit in 512x512
            if w > 0 and w < 256:
                factor = 256 // w
                if factor > 1:
                    self.icon_image = self.icon_image.zoom(factor)
            elif w > 512:
                factor = w // 512
                if factor > 1:
                    self.icon_image = self.icon_image.subsample(factor)
                    
            self.icon_label.config(image=self.icon_image, text="")
        except (Exception, tk.TclError):
            self._set_icon_text_safe("Display Error")

    def _show_icon_context_menu(self, event):
        icon_path = getattr(self, 'icon_path', None) or self._get_default_icon_path()
        if icon_path and os.path.isfile(icon_path):
            self.icon_menu.tk_popup(event.x_root, event.y_root)

    def _save_app_icon(self):
        icon_path = getattr(self, 'icon_path', None) or self._get_default_icon_path()
        if not icon_path or not os.path.isfile(icon_path):
            messagebox.showwarning("Save App Icon", "App icon is not loaded or not available.", parent=self)
            return

        pkg = self.app_info.get('package', 'app')
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Save App Icon",
            defaultextension=".png",
            initialfile=f"{pkg}_icon.png",
            filetypes=[("PNG Image", "*.png"), ("All Files", "*.*")]
        )
        if dest:
            try:
                shutil.copy2(icon_path, dest)
                messagebox.showinfo("Save App Icon", f"App icon successfully saved to:\n{dest}", parent=self)
            except Exception as exc:
                messagebox.showerror("Save App Icon Error", f"Failed to save icon file:\n{exc}", parent=self)
