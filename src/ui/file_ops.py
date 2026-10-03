"""FileManager mixin: mutating operations and the context menu."""

import posixpath
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, simpledialog
from .file_dialogs import FolderSelectorDialog


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

        menu.add_command(label="Download", command=self._download_file, state=download_state)
        menu.add_command(label="Upload", command=self._upload_file, state=upload_state)
        menu.add_command(label="New Folder", command=self._create_folder, state=upload_state)


        menu.add_separator()

        menu.add_command(label="Rename", command=self._rename_file, state=write_state)
        menu.add_command(label="Copy To...", command=self._copy_file, state=download_state)
        menu.add_command(label="Move To...", command=self._move_file, state=write_state)
        menu.add_command(label="Delete", command=self._delete_file, state=write_state)

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

