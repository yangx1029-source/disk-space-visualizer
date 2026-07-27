"""Small Windows-friendly graphical launcher for diskvis."""

from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from pathlib import Path, PurePath
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk
from typing import Any

from diskvis import __version__
from diskvis.formatter import parse_size
from diskvis.models import AnalysisCancelled, CancellationToken
from diskvis.report import generate_comparison_report, generate_html_report
from diskvis.scanner import DEFAULT_IGNORE_DIRS
from diskvis.service import AnalysisOptions, AnalysisResult, analyze_directory
from diskvis.snapshot import (
    compare_snapshots,
    comparison_to_data,
    load_snapshot,
    save_snapshot,
)


def default_report_name(folder: PurePath) -> str:
    """Return a readable report name, including for drive and filesystem roots."""
    root_name = folder.name or folder.drive.rstrip(":\\/") or "root"
    return f"{root_name}-report.html"


class DiskVisWindow:
    """Tkinter window that runs the existing diskvis analysis pipeline."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"Disk Space Visualizer v{__version__}")
        self.root.geometry("760x520")
        self.root.minsize(680, 440)

        self.folder_var = tk.StringVar()
        self.output_var = tk.StringVar(
            value=str(Path.home() / "diskvis-reports" / "report.html")
        )
        self.min_size_var = tk.StringVar()
        self.top_var = tk.IntVar(value=10)
        self.offline_var = tk.BooleanVar(value=True)
        self.duplicates_var = tk.BooleanVar(value=False)
        self.save_snapshot_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="请选择要分析的文件夹")
        self.queue: Queue[tuple[str, Any]] = Queue()
        self.last_report: Path | None = None
        self.cancel_token: CancellationToken | None = None
        self.worker_thread: threading.Thread | None = None
        self.closing = False

        self._build_widgets()
        self.root.after(100, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_widgets(self) -> None:
        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=1)

        title = ttk.Label(
            frame,
            text=f"Disk Space Visualizer v{__version__}",
            font=("Segoe UI", 18, "bold"),
        )
        title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))

        ttk.Label(frame, text="扫描文件夹").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.folder_var).grid(
            row=1, column=1, sticky="ew", padx=8, pady=5
        )
        ttk.Button(frame, text="选择...", command=self._choose_folder).grid(
            row=1, column=2, pady=5
        )

        ttk.Label(frame, text="报告输出路径").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.output_var).grid(
            row=2, column=1, sticky="ew", padx=8, pady=5
        )
        ttk.Button(frame, text="另存为...", command=self._choose_output).grid(
            row=2, column=2, pady=5
        )

        ttk.Label(frame, text="最小文件大小").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.min_size_var, width=16).grid(
            row=3, column=1, sticky="w", padx=8, pady=5
        )
        ttk.Label(frame, text="例如 100MB，留空表示全部文件").grid(
            row=3, column=2, sticky="w", pady=5
        )

        options = ttk.Frame(frame)
        options.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 12))
        ttk.Label(options, text="Top N").pack(side=tk.LEFT)
        ttk.Spinbox(options, from_=1, to=100, textvariable=self.top_var, width=6).pack(
            side=tk.LEFT, padx=(8, 18)
        )
        ttk.Checkbutton(options, text="离线报告", variable=self.offline_var).pack(
            side=tk.LEFT, padx=(0, 18)
        )
        ttk.Checkbutton(options, text="检测重复文件", variable=self.duplicates_var).pack(
            side=tk.LEFT
        )

        ttk.Checkbutton(
            options, text="Save Snapshot", variable=self.save_snapshot_var
        ).pack(side=tk.LEFT, padx=(18, 0))
        ttk.Button(
            options, text="Compare Snapshots", command=self._open_comparison_dialog
        ).pack(side=tk.LEFT, padx=(18, 0))

        self.generate_button = ttk.Button(
            frame, text="开始分析并生成报告", command=self._start_generation
        )
        self.generate_button.grid(row=5, column=0, sticky="w", pady=(0, 12))
        self.cancel_button = ttk.Button(
            frame, text="Cancel", command=self._cancel_generation, state=tk.DISABLED
        )
        self.cancel_button.grid(row=5, column=1, sticky="w", padx=(8, 0), pady=(0, 12))
        self.open_button = ttk.Button(
            frame, text="打开最近报告", command=self._open_report, state=tk.DISABLED
        )
        self.open_button.grid(row=5, column=2, sticky="e", pady=(0, 12))

        ttk.Label(frame, textvariable=self.status_var).grid(
            row=6, column=0, columnspan=3, sticky="nw", pady=(0, 6)
        )
        self.log = tk.Text(frame, height=10, state=tk.DISABLED, wrap=tk.WORD)
        self.log.grid(row=7, column=0, columnspan=3, sticky="nsew")
        frame.rowconfigure(7, weight=1)

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="选择要扫描的文件夹")
        if selected:
            self.folder_var.set(selected)
            folder = Path(selected)
            self.output_var.set(
                str(Path.home() / "diskvis-reports" / default_report_name(folder))
            )

    def _choose_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="保存 HTML 报告",
            defaultextension=".html",
            filetypes=[("HTML 报告", "*.html"), ("所有文件", "*.*")],
        )
        if selected:
            self.output_var.set(selected)

    def _open_comparison_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Snapshot History Comparison")
        dialog.geometry("680x250")
        dialog.minsize(600, 220)
        dialog.transient(self.root)

        old_var = tk.StringVar()
        new_var = tk.StringVar()
        output_var = tk.StringVar(
            value=str(Path.home() / "diskvis-reports" / "comparison.html")
        )
        dialog.columnconfigure(1, weight=1)

        def add_path_row(row: int, label: str, variable: tk.StringVar) -> None:
            ttk.Label(dialog, text=label).grid(row=row, column=0, padx=12, pady=8, sticky="w")
            ttk.Entry(dialog, textvariable=variable).grid(
                row=row, column=1, padx=8, pady=8, sticky="ew"
            )
            ttk.Button(
                dialog,
                text="Browse",
                command=lambda: self._choose_snapshot(variable),
            ).grid(row=row, column=2, padx=12, pady=8)

        add_path_row(0, "Older snapshot", old_var)
        add_path_row(1, "Newer snapshot", new_var)
        ttk.Label(dialog, text="HTML output").grid(row=2, column=0, padx=12, pady=8, sticky="w")
        ttk.Entry(dialog, textvariable=output_var).grid(
            row=2, column=1, padx=8, pady=8, sticky="ew"
        )

        def generate() -> None:
            try:
                old = load_snapshot(Path(old_var.get()).expanduser())
                new = load_snapshot(Path(new_var.get()).expanduser())
                data = comparison_to_data(compare_snapshots(old, new))
                output = Path(output_var.get()).expanduser()
                generate_comparison_report(data, output)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Comparison failed", str(exc), parent=dialog)
                return
            self.last_report = output
            self.open_button.configure(state=tk.NORMAL)
            self._write_log(f"Comparison report generated: {output}")
            messagebox.showinfo("Comparison complete", str(output), parent=dialog)

        ttk.Button(dialog, text="Generate Comparison", command=generate).grid(
            row=3, column=1, pady=12, sticky="w"
        )

    @staticmethod
    def _choose_snapshot(variable: tk.StringVar) -> None:
        selected = filedialog.askopenfilename(
            title="Choose snapshot JSON",
            filetypes=[("Snapshot JSON", "*.json"), ("All files", "*.*")],
        )
        if selected:
            variable.set(selected)

    def _start_generation(self) -> None:
        folder = Path(self.folder_var.get()).expanduser()
        output = Path(self.output_var.get()).expanduser()
        if not folder.is_dir():
            messagebox.showerror("路径错误", "请选择一个存在的文件夹。")
            return
        if not output.name:
            messagebox.showerror("路径错误", "请选择 HTML 报告输出文件。")
            return

        try:
            top = int(self.top_var.get())
            if top < 1:
                raise ValueError
            min_size = parse_size(self.min_size_var.get()) if self.min_size_var.get() else 0
        except ValueError:
            messagebox.showerror("参数错误", "Top N 必须是正整数，最小大小应类似 100MB。")
            return

        include_duplicates = self.duplicates_var.get()
        offline = self.offline_var.get()
        save_snapshot_enabled = self.save_snapshot_var.get()
        self.cancel_token = CancellationToken()
        self.generate_button.configure(state=tk.DISABLED)
        self.cancel_button.configure(state=tk.NORMAL)
        self.open_button.configure(state=tk.DISABLED)
        self._write_log(f"开始扫描：{folder}")
        thread = threading.Thread(
            target=self._generate_in_background,
            args=(
                folder,
                output,
                top,
                min_size,
                include_duplicates,
                offline,
                save_snapshot_enabled,
                self.cancel_token,
            ),
            daemon=True,
        )
        self.worker_thread = thread
        thread.start()

    def _generate_in_background(
        self,
        folder: Path,
        output: Path,
        top: int,
        min_size: int,
        include_duplicates: bool,
        offline: bool,
        save_snapshot_enabled: bool,
        cancellation: CancellationToken,
    ) -> None:
        file_count = 0
        last_log_at = 0.0

        def on_item(path: Path, is_dir: bool) -> None:
            nonlocal file_count, last_log_at
            if is_dir:
                return
            file_count += 1
            now = time.monotonic()
            if file_count == 1 or now - last_log_at >= 0.5:
                self.queue.put(("log", f"已扫描 {file_count} 个文件：{path.name}"))
                last_log_at = now

        try:
            result = analyze_directory(
                AnalysisOptions(
                    root=folder,
                    top=top,
                    min_size=min_size,
                    ignore_dirs=DEFAULT_IGNORE_DIRS,
                    include_duplicates=include_duplicates,
                    cancellation=cancellation,
                ),
                on_item=on_item,
            )
            cancellation.raise_if_cancelled()
            generate_html_report(result.data, output, offline=offline)
            if save_snapshot_enabled:
                snapshot_path = save_snapshot(result)
                self.queue.put(("log", f"Snapshot saved: {snapshot_path}"))
        except AnalysisCancelled:
            self.queue.put(("cancelled", None))
            return
        except Exception as exc:
            # This is the GUI worker boundary; every failure must restore the UI.
            self.queue.put(("error", str(exc)))
            return
        self.queue.put(("done", (output, result)))

    def _restore_idle_state(self) -> None:
        self.generate_button.configure(state=tk.NORMAL)
        self.cancel_button.configure(state=tk.DISABLED)
        self.open_button.configure(
            state=(
                tk.NORMAL
                if self.last_report and self.last_report.exists()
                else tk.DISABLED
            )
        )
        self.worker_thread = None
        self.cancel_token = None

    def _cancel_generation(self) -> None:
        if self.cancel_token:
            self.cancel_token.cancel()
            self.status_var.set("Cancelling...")
            self._write_log("Cancellation requested; waiting for the worker to stop.")

    def _on_close(self) -> None:
        self.closing = True
        if self.worker_thread and self.worker_thread.is_alive():
            self._cancel_generation()
            return
        self.root.destroy()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, value = self.queue.get_nowait()
                if kind == "log":
                    self._write_log(value)
                elif kind == "error":
                    self._restore_idle_state()
                    self.open_button.configure(
                        state=(
                            tk.NORMAL
                            if self.last_report and self.last_report.exists()
                            else tk.DISABLED
                        )
                    )
                    messagebox.showerror("生成失败", value)
                    self.status_var.set("生成失败，请检查路径和权限")
                    self._write_log(f"生成失败：{value}")
                elif kind == "cancelled":
                    self._restore_idle_state()
                    self.status_var.set("Analysis cancelled")
                    self._write_log("Analysis cancelled; no report was written.")
                else:
                    output, result = value
                    self.last_report = Path(output)
                    self._restore_idle_state()
                    self.status_var.set(f"报告已生成：{output}")
                    self._write_log(self._completion_message(output, result))
        except Empty:
            pass
        if self.closing and not (self.worker_thread and self.worker_thread.is_alive()):
            self.root.destroy()
            return
        self.root.after(100, self._poll_queue)

    @staticmethod
    def _completion_message(output: Path, result: AnalysisResult) -> str:
        duplicate_text = (
            f"，重复文件 {result.duplicate_group_count} 组"
            if result.duplicates_scanned
            else ""
        )
        return (
            f"完成：扫描 {result.scanned_file_count} 个文件、"
            f"{result.scanned_folder_count} 个文件夹{duplicate_text}；报告：{output}"
        )

    def _open_report(self) -> None:
        if self.last_report and self.last_report.exists():
            os.startfile(str(self.last_report))

    def _write_log(self, message: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)


def main() -> None:
    root = tk.Tk()
    DiskVisWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
