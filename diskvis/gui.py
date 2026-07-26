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
from diskvis.report import generate_html_report
from diskvis.scanner import DEFAULT_IGNORE_DIRS
from diskvis.service import AnalysisOptions, AnalysisResult, analyze_directory


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
        self.status_var = tk.StringVar(value="请选择要分析的文件夹")
        self.queue: Queue[tuple[str, Any]] = Queue()
        self.last_report: Path | None = None

        self._build_widgets()
        self.root.after(100, self._poll_queue)

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

        self.generate_button = ttk.Button(
            frame, text="开始分析并生成报告", command=self._start_generation
        )
        self.generate_button.grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 12))
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
        self.generate_button.configure(state=tk.DISABLED)
        self.open_button.configure(state=tk.DISABLED)
        self._write_log(f"开始扫描：{folder}")
        thread = threading.Thread(
            target=self._generate_in_background,
            args=(folder, output, top, min_size, include_duplicates, offline),
            daemon=True,
        )
        thread.start()

    def _generate_in_background(
        self,
        folder: Path,
        output: Path,
        top: int,
        min_size: int,
        include_duplicates: bool,
        offline: bool,
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
                ),
                on_item=on_item,
            )
            generate_html_report(result.data, output, offline=offline)
        except Exception as exc:
            # This is the GUI worker boundary; every failure must restore the UI.
            self.queue.put(("error", str(exc)))
            return
        self.queue.put(("done", (output, result)))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, value = self.queue.get_nowait()
                if kind == "log":
                    self._write_log(value)
                elif kind == "error":
                    self.generate_button.configure(state=tk.NORMAL)
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
                else:
                    output, result = value
                    self.last_report = Path(output)
                    self.generate_button.configure(state=tk.NORMAL)
                    self.open_button.configure(state=tk.NORMAL)
                    self.status_var.set(f"报告已生成：{output}")
                    self._write_log(self._completion_message(output, result))
        except Empty:
            pass
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
