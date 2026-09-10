from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from recorder.recovery import delete_session, recover_session, scan_recoverable
from recorder.utils import open_in_file_manager

BG = "#f5f5f2"
WHITE = "#ffffff"
TEXT = "#161616"
MUTED = "#6f6f6a"
LINE = "#ddddda"
DARK = "#1d1d1b"


class RecoveryDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, save_dir: str | Path) -> None:
        super().__init__(parent)
        self.save_dir = Path(save_dir)
        self.items = []
        self.title("ResiliCapture Recovery")
        self.geometry("860x470")
        self.minsize(720, 390)
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()
        self._configure_styles()
        self._build()
        self.refresh()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.configure("Recovery.Treeview", background=WHITE, fieldbackground=WHITE, foreground=TEXT, rowheight=30, bordercolor=LINE, font=("Segoe UI", 9))
        style.configure("Recovery.Treeview.Heading", background="#eeeeeb", foreground=TEXT, font=("Segoe UI Semibold", 9), relief="flat")
        style.map("Recovery.Treeview", background=[("selected", "#ddddda")], foreground=[("selected", TEXT)])

    def _build(self) -> None:
        header = tk.Frame(self, bg=WHITE, height=78, highlightthickness=1, highlightbackground=LINE)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="Recovery Center", font=("Segoe UI Semibold", 16), fg=TEXT, bg=WHITE).pack(anchor="w", padx=22, pady=(16, 2))
        tk.Label(header, text="Recover sealed recording segments after a crash, capture failure, or shutdown.", font=("Segoe UI", 9), fg=MUTED, bg=WHITE).pack(anchor="w", padx=22)

        body = tk.Frame(self, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        body.pack(fill="both", expand=True, padx=18, pady=18)
        columns = ("created", "state", "segments", "size", "error")
        self.tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="browse", style="Recovery.Treeview")
        for key, text in [("created", "Created"), ("state", "State"), ("segments", "Segments"), ("size", "Size"), ("error", "Last error")]:
            self.tree.heading(key, text=text)
        self.tree.column("created", width=165, anchor="w")
        self.tree.column("state", width=90, anchor="center")
        self.tree.column("segments", width=75, anchor="center")
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("error", width=330, anchor="w")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=10)

        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=18, pady=(0, 18))
        self.status = tk.Label(footer, text="", font=("Segoe UI", 9), fg=MUTED, bg=BG)
        self.status.pack(side="left")
        ttk.Button(footer, text="Refresh", command=self.refresh).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Delete", command=self.delete_selected).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Open folder", command=self.open_selected).pack(side="right", padx=(8, 0))
        self.recover_button = ttk.Button(footer, text="Recover", style="Dark.TButton", command=self.recover_selected)
        self.recover_button.pack(side="right")

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"

    def refresh(self) -> None:
        self.items = scan_recoverable(self.save_dir)
        for row in self.tree.get_children():
            self.tree.delete(row)
        for index, item in enumerate(self.items):
            created = item.created_utc.replace("T", " ")[:19]
            error = item.error.replace("\n", " ")[:120]
            self.tree.insert("", "end", iid=str(index), values=(created, item.state, item.segment_count, self._format_size(item.bytes_total), error))
        self.status.configure(text=f"{len(self.items)} recoverable recording{'s' if len(self.items) != 1 else ''}")

    def _selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Recovery Center", "Select a project first.", parent=self)
            return None
        try:
            return self.items[int(selection[0])]
        except (IndexError, ValueError):
            return None

    def open_selected(self) -> None:
        item = self._selected()
        if item:
            open_in_file_manager(item.session_dir)

    def delete_selected(self) -> None:
        item = self._selected()
        if not item:
            return
        if not messagebox.askyesno("Delete recovery project", "Permanently delete all recoverable segments in this project?", parent=self):
            return
        try:
            delete_session(item.session_dir)
            self.refresh()
        except OSError as exc:
            messagebox.showerror("Delete failed", str(exc), parent=self)

    def recover_selected(self) -> None:
        item = self._selected()
        if not item:
            return
        self.recover_button.configure(state="disabled")
        self.status.configure(text="Recovering and verifying the recording…")

        def work() -> None:
            try:
                output = recover_session(item.session_dir, self.save_dir)
                self.after(0, lambda: self._recovery_done(item.session_dir, output))
            except Exception as exc:
                self.after(0, lambda: self._recovery_failed(str(exc)))

        threading.Thread(target=work, name="ResiliCaptureRecovery", daemon=True).start()

    def _recovery_done(self, session_dir: Path, output: Path) -> None:
        self.recover_button.configure(state="normal")
        self.refresh()
        if messagebox.askyesno(
            "Recovery complete",
            f"Recovered and verified:\n{output}\n\nOpen the output folder?",
            parent=self,
        ):
            open_in_file_manager(output.parent)

    def _recovery_failed(self, error: str) -> None:
        self.recover_button.configure(state="normal")
        self.status.configure(text="Recovery failed")
        messagebox.showerror("Recovery failed", error, parent=self)
