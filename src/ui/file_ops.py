"""FileManager mixin: mutating operations and the context menu."""

import hashlib
import os
import posixpath
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, simpledialog
from .file_dialogs import FolderSelectorDialog

# Small, likely-text files offered remote editing (pull/edit/watch/push round trip).
_EDITABLE_EXTENSIONS = ('.txt', '.xml', '.json', '.log', '.ini', '.cfg',
                        '.conf', '.md', '.properties')
_EDIT_MAX_BYTES = 2 * 1024 * 1024
_EDIT_POLL_MS = 3000


class _FileOpsMixin:
    """_FileOpsMixin (see file_manager.py)."""

    def _rename_file(self):
        if getattr(self, '_loading', False):
            return
        selection = self.file_tree.selection()
        if not selection: return
        
        item_id = selection[0]
        item = self.file_tree.item(item_id)
        old_name = item['values'][0]
        
        new_name = simpledialog.askstring("Rename", f"Enter new name for '{old_name}':", initialvalue=old_name)
        if new_name is None:
            return
            
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
            
        if new_name in ('.', '..'):
            messagebox.showerror("Invalid Filename", "Filename cannot be '.' or '..'.")
            return
            
        FORBIDDEN_CHARS = set('/\\0;&|`$()<>"\'*?\n\r\t')
        if any(c in FORBIDDEN_CHARS for c in new_name):
            messagebox.showerror("Invalid Filename", "Filename contains invalid characters or shell metacharacters.\n\nForbidden characters: / \\ ; & | ` $ ( ) < > \" ' * ?")
            return

        if len(new_name.encode('utf-8')) > 255:
            messagebox.showerror("Invalid Filename", "Filename is too long (maximum 255 bytes).")
            return
            
        if self.config.get('file_manager', 'confirm_rename', True):
            if not messagebox.askyesno("Confirm Rename", f"Are you sure you want to rename '{old_name}' to '{new_name}'?"):
                return
            
        old_path = self.current_path.rstrip('/') + '/' + old_name
        new_path = self.current_path.rstrip('/') + '/' + new_name
        
        try:
            self.device_manager.rename_file(self.selected_device, old_path, new_path)
            self.invalidate_cache()
            self.refresh()
            self._set_status(f"Renamed '{old_name}' to '{new_name}'")
        except Exception as e:
            self._show_error("Rename Error", str(e))

    def _copy_file(self):
        self._move_copy_operation(copy=True)

    def _move_file(self):
        self._move_copy_operation(copy=False)

    def _move_copy_operation(self, copy=True):
        if getattr(self, '_loading', False):
            return
        selection = self.file_tree.selection()
        if not selection: return
        
        item_id = selection[0]
        item = self.file_tree.item(item_id)
        filename = item['values'][0]
        is_dir = 'directory' in item.get('tags', ())
        src_path = self.current_path.rstrip('/') + '/' + filename
        
        dialog = FolderSelectorDialog(self.frame.winfo_toplevel(), self.device_manager, self.current_path)
        dialog.start(self.selected_device)
        self.frame.wait_window(dialog)
        
        if dialog.selected_path:
            dest_path = dialog.selected_path.rstrip('/') + '/' + filename
            
            src_norm = posixpath.normpath(src_path)
            dest_norm = posixpath.normpath(dest_path)
            
            op_name = "copy" if copy else "move"
            
            if src_norm == dest_norm:
                messagebox.showwarning("Invalid Destination", f"Cannot {op_name} '{filename}' to the same location.")
                return
                
            if is_dir and dest_norm.startswith(src_norm + '/'):
                messagebox.showerror("Invalid Destination", f"Cannot {op_name} directory '{filename}' into its own subdirectory:\n\n{dialog.selected_path}")
                return

            # Check if destination file/folder already exists on device
            try:
                check_cmd = ['shell', f'[ -e "{dest_path}" ] && echo 1 || echo 0']
                res = self.device_manager.adb._run_command(check_cmd, self.selected_device)
                dest_exists = (res.strip() == '1')
            except Exception:
                dest_exists = False
                
            if dest_exists:
                msg = f"The destination already contains an item named '{filename}':\n\n{dest_path}\n\nDo you want to overwrite it?"
                if not messagebox.askyesno("Confirm Overwrite", msg, icon=messagebox.WARNING):
                    return
            
            def task():
                try:
                    if copy:
                        self.device_manager.copy_file(self.selected_device, src_path, dest_path)
                    else:
                        self.device_manager.move_file(self.selected_device, src_path, dest_path)
                    
                    op_title = "Copied" if copy else "Moved"
                    self.invalidate_cache()
                    self.frame.after(0, self.refresh)
                    self.frame.after(0, lambda: (
                        messagebox.showinfo("Success", f"{op_title} '{filename}' successfully"),
                        self._set_status(f"{op_title} '{filename}' to {dialog.selected_path}")
                    ))
                except Exception as e:
                    msg = str(e)
                    self.frame.after(0, lambda: self._show_error("Operation Error", msg))
            
            self._set_status(f"{'Copying' if copy else 'Moving'} '{filename}'...")
            threading.Thread(target=task, daemon=True).start()

    def _download_file(self):
        if getattr(self, '_loading', False):
            return
        if not self._require_device():
            return
            
        selection = self.file_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a file or directory to download")
            return
            
        item_id = selection[0]
        item = self.file_tree.item(item_id)
        is_directory = 'directory' in item['tags']
        filename = item['values'][0]
        
        if is_directory:
            # For directories, let user choose a folder location
            local_path = filedialog.askdirectory(title=f"Select destination for '{filename}'")
            if local_path:
                # adb pull will create the directory inside the selected location
                local_path = str(Path(local_path) / filename)
        else:
            local_path = filedialog.asksaveasfilename(initialfile=filename)
        
        if not local_path:
            return
            
        remote_path = self.current_path.rstrip('/') + '/' + filename
        
        def task():
            try:
                if is_directory:
                    self.frame.after(0, lambda: self._set_status(f"Downloading directory {filename}..."))
                    # adb pull handles directories recursively
                    self.device_manager.download_file(self.selected_device, remote_path, local_path)
                    self.frame.after(0, lambda: (
                        messagebox.showinfo("Success", f"Directory downloaded successfully to:\n{local_path}"),
                        self._set_status(f"Downloaded {filename}")
                    ))
                else:
                    self.frame.after(0, lambda: self._set_status(f"Downloading {filename}..."))
                    self.device_manager.download_file(self.selected_device, remote_path, local_path)
                    self.frame.after(0, lambda: (
                        messagebox.showinfo("Success", "File downloaded successfully"),
                        self._set_status(f"Downloaded {filename}")
                    ))
            except Exception as e:
                msg = str(e)
                self.frame.after(0, lambda: (
                    self._show_error("Download Error", msg),
                    self._set_status(f"Download failed")
                ))
        
        self._set_status("Processing...")
        threading.Thread(target=task, daemon=True).start()

    def _upload_file(self):
        if getattr(self, '_loading', False):
            return
        if not self._require_device():
            return
            
        local_path = filedialog.askopenfilename()
        if not local_path:
            return
            
        filename = Path(local_path).name
        remote_path = self.current_path.rstrip('/') + '/' + filename
        
        # Check if remote file/directory already exists on device
        try:
            check_cmd = ['shell', f'[ -e "{remote_path}" ] && echo 1 || echo 0']
            res = self.device_manager.adb._run_command(check_cmd, self.selected_device)
            remote_exists = (res.strip() == '1')
        except Exception:
            remote_exists = False
            
        if remote_exists:
            msg = f"A file or directory named '{filename}' already exists at:\n\n{remote_path}\n\nDo you want to overwrite it?"
            if not messagebox.askyesno("Confirm Overwrite", msg, icon=messagebox.WARNING):
                return
        
        def task():
            try:
                self.device_manager.upload_file(self.selected_device, local_path, remote_path)
                self.invalidate_cache()
                self.frame.after(0, self.refresh)
                self.frame.after(0, lambda: (
                    messagebox.showinfo("Success", f"File '{filename}' uploaded successfully"),
                    self._set_status(f"Uploaded '{filename}' to {self.current_path}")
                ))
            except Exception as e:
                msg = str(e)
                self.frame.after(0, lambda: self._show_error("Upload Error", msg))
        
        self._set_status(f"Uploading {filename}...")
        threading.Thread(target=task, daemon=True).start()

    def _delete_file(self):
        if getattr(self, '_loading', False):
            return
        if not self._require_device():
            return
            
        selection = self.file_tree.selection()
        if not selection:
            return
            
        item_id = selection[0]
        item = self.file_tree.item(item_id)
        filename = item['values'][0]
        remote_path = self.current_path.rstrip('/') + '/' + filename
        
        is_dir = 'directory' in item.get('tags', ())
        item_type = "directory (and all its contents)" if is_dir else "file"
        msg = f"Are you sure you want to permanently delete this {item_type}?\n\nFull Path:\n{remote_path}"
        
        if not messagebox.askyesno("Confirm Delete", msg, icon=messagebox.WARNING):
            return
            
        try:
            self.device_manager.delete_file(self.selected_device, remote_path)
            self.invalidate_cache()
            self.refresh()
            self._set_status(f"Deleted: {remote_path}")
        except Exception as e:
            self._show_error("Delete Error", str(e))

    def _create_folder(self):
        if getattr(self, '_loading', False):
            return
        if not self._require_device():
            return
            
        folder_name = simpledialog.askstring("New Folder", "Enter name of the new folder:", parent=self.frame.winfo_toplevel())
        if folder_name is None:
            return
            
        folder_name = folder_name.strip()
        if not folder_name:
            return
            
        if folder_name in ('.', '..'):
            messagebox.showerror("Invalid Folder Name", "Folder name cannot be '.' or '..'.")
            return

        if folder_name.startswith('-'):
            messagebox.showerror("Invalid Folder Name", "Folder name cannot start with a hyphen ('-').")
            return
            
        FORBIDDEN_CHARS = set('/\\0;&|`$()<>"\'*?\n\r\t')
        if any(c in FORBIDDEN_CHARS for c in folder_name):
            messagebox.showerror("Invalid Folder Name", "Folder name contains invalid characters or shell metacharacters.\n\nForbidden characters: / \\ ; & | ` $ ( ) < > \" ' * ?")
            return

        if len(folder_name.encode('utf-8')) > 255:
            messagebox.showerror("Invalid Folder Name", "Folder name is too long (maximum 255 bytes).")
            return
            
        remote_path = self.current_path.rstrip('/') + '/' + folder_name
        
        def task():
            try:
                self.device_manager.make_directory(self.selected_device, remote_path)
                self.invalidate_cache()
                self.frame.after(0, self.refresh)
                self.frame.after(0, lambda: self._set_status(f"Created folder: {folder_name}"))
            except Exception as e:
                msg = str(e)
                self.frame.after(0, lambda: self._show_error("Create Folder Error", msg))

                
        self._set_status("Creating folder...")
        threading.Thread(target=task, daemon=True).start()

    def _show_context_menu(self, event):
        if getattr(self, '_loading', False):
            return
        item_id = self.file_tree.identify_row(event.y)
        if item_id:
            # Select the item under mouse cursor
            self.file_tree.selection_set(item_id)
            self.file_tree.focus(item_id)
            self._update_selection_buttons()

            self._popup_context_menu(event.x_root, event.y_root)

    def _popup_context_menu(self, x_root, y_root):
        """Build and show the file context menu once, shared by list and grid."""
        menu = tk.Menu(self.frame, tearoff=0)

        # Copy items at the top
        menu.add_command(label="Copy Full Path", command=self._context_copy_full_path)
        menu.add_command(label="Copy Filename", command=self._context_copy_filename)

        menu.add_separator()

        # Options matching bottom buttons
        has_selection = bool(self.file_tree.selection()) and self.selected_device is not None
        is_writable = getattr(self, 'is_current_path_writable', False)

        download_state = tk.NORMAL if has_selection else tk.DISABLED
        write_state = tk.NORMAL if (is_writable and has_selection) else tk.DISABLED
        upload_state = tk.NORMAL if is_writable else tk.DISABLED

        selected_info = self._context_selection_info()
        edit_state = tk.NORMAL if self._is_editable_file(selected_info) else tk.DISABLED

        menu.add_command(label="Download", command=self._download_file, state=download_state)
        menu.add_command(label="Upload", command=self._upload_file, state=upload_state)
        menu.add_command(label="New Folder", command=self._create_folder, state=upload_state)


        menu.add_separator()

        menu.add_command(label="Edit...", command=self._edit_file, state=edit_state)
        menu.add_command(label="Rename", command=self._rename_file, state=write_state)
        menu.add_command(label="Copy To...", command=self._copy_file, state=download_state)
        menu.add_command(label="Move To...", command=self._move_file, state=write_state)
        menu.add_command(label="Delete", command=self._delete_file, state=write_state)

        watch_key = None
        if selected_info is not None and self.selected_device:
            watch_key = (self.selected_device, selected_info.get('full_path'))
        if watch_key in getattr(self, '_edit_watches', {}):
            menu.add_command(
                label=f"Stop Watching '{selected_info.get('name')}'",
                command=lambda key=watch_key: self._stop_edit_watch(key))

        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _context_copy_full_path(self):
        selection = self.file_tree.selection()
        if not selection:
            return
        item_id = selection[0]
        file_info = self.files_data.get(item_id)
        if file_info:
            path = file_info.get('full_path', '')
            self.frame.clipboard_clear()
            self.frame.clipboard_append(path)
            self._set_status(f"Copied full path: {path}")

    def _context_copy_filename(self):
        selection = self.file_tree.selection()
        if not selection:
            return
        item_id = selection[0]
        file_info = self.files_data.get(item_id)
        if file_info:
            name = file_info.get('name', '')
            self.frame.clipboard_clear()
            self.frame.clipboard_append(name)
            self._set_status(f"Copied filename: {name}")

    # -- remote text-file editing (pull, watch, push back) -----------------------

    def _context_selection_info(self):
        """Info dict of the single selected row, else None."""
        selection = self.file_tree.selection()
        if len(selection) != 1:
            return None
        return self.files_data.get(selection[0])

    def _is_editable_file(self, info):
        """True for a regular file with a small, likely-text extension."""
        if not info or info.get('is_dir'):
            return False
        name = (info.get('name') or '').lower()
        return any(name.endswith(ext) for ext in _EDITABLE_EXTENSIONS)

    def _edit_file(self):
        if getattr(self, '_loading', False):
            return
        if not self._require_device():
            return
        info = self._context_selection_info()
        name = (info.get('name') if info else '') or ''
        if not self._is_editable_file(info):
            messagebox.showinfo("Edit", f"'{name}' is not an editable text file type.")
            return
        raw = str(info.get('size_raw') or '')
        if not raw.isdigit():
            messagebox.showinfo(
                "Edit",
                f"The size of '{name}' could not be determined, so it was not opened for editing.")
            return
        if int(raw) > _EDIT_MAX_BYTES:
            messagebox.showinfo(
                "Edit",
                f"'{name}' is too large to edit remotely (over 2 MB).\n\n"
                "Download it and edit a local copy instead.")
            return

        remote_path = info.get('full_path') or (self.current_path.rstrip('/') + '/' + name)
        key = (self.selected_device, remote_path)
        digest = hashlib.sha1(
            f"{self.selected_device}\0{remote_path}".encode('utf-8', 'replace')).hexdigest()[:12]
        safe_name = re.sub(r'[^A-Za-z0-9._\-]', '_', name) or 'file'
        local_dir = Path(self.config.get_cache_dir('remote_edit')) / digest
        local_path = local_dir / safe_name
        device_id = self.selected_device

        def task():
            try:
                local_dir.mkdir(parents=True, exist_ok=True)
                self.device_manager.download_file(device_id, remote_path, str(local_path))
                stat = local_path.stat()
                fingerprint = (stat.st_mtime_ns, stat.st_size)
            except Exception as e:
                msg = str(e)
                self.frame.after(0, lambda: self._show_error("Edit Error", msg))
                return

            def open_editor():
                old = self._edit_watches.get(key)
                if old and old.get('after_id') is not None:
                    try:
                        self.frame.after_cancel(old['after_id'])
                    except Exception:
                        pass
                watch = {'local_path': str(local_path), 'name': name,
                         'remote_path': remote_path,
                         'fingerprint': fingerprint, 'after_id': None}
                self._edit_watches[key] = watch
                try:
                    os.startfile(str(local_path))
                except OSError as e:
                    self._edit_watches.pop(key, None)
                    self._set_status(f"Could not open an editor for '{name}': {e}")
                    return
                watch['after_id'] = self.frame.after(
                    _EDIT_POLL_MS, lambda: self._poll_edit_watch(key))
                self._set_status(f"Watching '{name}' for edits ({remote_path})")
            self.frame.after(0, open_editor)

        self._set_status(f"Pulling '{name}' for editing...")
        threading.Thread(target=task, daemon=True).start()

    def _poll_edit_watch(self, key):
        watch = self._edit_watches.get(key)
        if watch is None:
            return
        try:
            if not self.frame.winfo_exists():
                return  # tab gone: stop silently
        except Exception:
            return
        local_path = Path(watch['local_path'])
        try:
            stat = local_path.stat()
        except OSError:
            self._edit_watches.pop(key, None)
            self._set_status(f"Stopped watching '{watch['name']}' (temp copy removed).")
            return
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        if fingerprint == watch['fingerprint']:
            watch['after_id'] = self.frame.after(
                _EDIT_POLL_MS, lambda: self._poll_edit_watch(key))
            return

        # Consume the change so the same edit is not offered twice.
        watch['fingerprint'] = fingerprint
        name = watch['name']
        push_it = messagebox.askyesno(
            "File Changed On Disk",
            f"'{name}' was modified while editing.\n\n"
            "Push the edited copy back to the device?")
        if self._edit_watches.get(key) is not watch:
            return  # canceled elsewhere meanwhile
        if not push_it:
            self._stop_edit_watch(key)
            self._set_status(f"Stopped watching '{name}'.")
            return

        def push_back():
            try:
                self.device_manager.upload_file(key[0], str(local_path), key[1])
                self.invalidate_cache()
                self.frame.after(0, self.refresh)
                self.frame.after(0, lambda: self._set_status(
                    f"Pushed edited '{name}' back to {key[1]}"))
            except Exception as e:
                msg = str(e)
                self.frame.after(0, lambda: self._show_error("Edit Push Error", msg))

        self._set_status(f"Pushing edited '{name}'...")
        threading.Thread(target=push_back, daemon=True).start()
        watch['after_id'] = self.frame.after(
            _EDIT_POLL_MS, lambda: self._poll_edit_watch(key))

    def _stop_edit_watch(self, key):
        """Cancel one watcher (user said no, or picked 'Stop Watching')."""
        watch = self._edit_watches.pop(key, None)
        if watch and watch.get('after_id') is not None:
            try:
                self.frame.after_cancel(watch['after_id'])
            except Exception:
                pass

    def _cancel_all_edit_watches(self):
        for key in list(getattr(self, '_edit_watches', {}) or {}):
            self._stop_edit_watch(key)

