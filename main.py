"""PDF脱敏工具 — tkinter 图形界面"""

import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime
import sys
import threading
import subprocess
import os
import ctypes

# ---- Windows 短路径转换（避免中文字符导致 Tesseract 文件系统错误） ----
def _short_path(path: Path) -> str:
    """Windows 上转换为 8.3 短路径名，避免 Unicode 编码问题。"""
    if sys.platform != "win32":
        return str(path)
    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 1024):
        return buf.value
    return str(path)

# ---- 便携版 Tesseract 自动发现 ----
_BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.resolve()))
_TESSERACT_BIN = _BASE_DIR / "tesseract" / "tesseract.exe"  # Windows 便携版
if not _TESSERACT_BIN.exists():
    _TESSERACT_BIN = _BASE_DIR / "tesseract" / "tesseract"  # macOS 便携版
if not _TESSERACT_BIN.exists():
    _TESSERACT_BIN = _BASE_DIR / "tesseract"  # macOS PyInstaller
_TESSERACT_FOUND = False
if _TESSERACT_BIN.exists():
    # 将 tesseract 目录加入 DLL 搜索路径（Windows 需要找到 leptonica 等 DLL）
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(_TESSERACT_BIN.parent))
    # 确保 tesseract 目录在 PATH 中（DLL 查找 + pytesseract 子进程调用）
    os.environ["PATH"] = str(_TESSERACT_BIN.parent) + os.pathsep + os.environ.get("PATH", "")
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = _short_path(_TESSERACT_BIN)
    _tessdata_dir = _short_path(_TESSERACT_BIN.parent / "tessdata")
    os.environ["TESSDATA_PREFIX"] = _tessdata_dir
    _TESSERACT_FOUND = True

import fitz
fitz.TOOLS.mupdf_warnings(False)

from desensitizer import Desensitizer
from patterns import PATTERN_LIST

# ---- 路径配置 ----

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ---- 主窗口 ----

class DesensitizerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PDF脱敏工具 — 电子病历敏感数据脱敏")
        self.root.geometry("960x680")
        self.root.minsize(800, 540)

        self.desensitizer = Desensitizer()
        self.desensitizer.set_progress_callback(self._on_progress)

        # 日志 Tesseract 状态
        if _TESSERACT_FOUND:
            self._tess_info = f"Tesseract: {_TESSERACT_BIN}"
        else:
            self._tess_info = f"Tesseract: 未找到 (已检查 {_BASE_DIR / 'tesseract'})，扫描件PDF将无法OCR识别"

        self.file_list: list[Path] = []
        self.check_vars: dict[str, tk.BooleanVar] = {}
        self.scan_results: dict[str, object] = {}
        self.is_processing = False

        self._build_ui()
        self._log(self._tess_info, "success" if _TESSERACT_FOUND else "warn")
        self._refresh_file_list()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self):
        # 标题
        header = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        header.pack(fill=tk.X)
        ttk.Label(
            header, text="PDF脱敏工具",
            font=("Helvetica", 16, "bold"),
        ).pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(
            header, textvariable=self.status_var,
            foreground="gray",
        ).pack(side=tk.RIGHT)

        # 主体：左右布局
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 4))

        # 左侧按钮区
        left = ttk.LabelFrame(main, text="操作", padding=(8, 8))
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        btn_opts = {"width": 16, "padding": (6, 4)}
        ttk.Button(left, text="🔍 扫描选中文件", command=self._scan_selected, **btn_opts).pack(pady=(0, 6))
        ttk.Button(left, text="🖊️ 执行脱敏", command=self._redact_selected, **btn_opts).pack(pady=(0, 12))

        ttk.Separator(left, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 8))

        ttk.Label(left, text="已知患者姓名:").pack(anchor=tk.W)
        self.known_name_var = tk.StringVar()
        ttk.Entry(left, textvariable=self.known_name_var, width=18).pack(pady=(2, 4))
        ttk.Label(left, text="（多个姓名用逗号分隔）", foreground="gray", font=("", 9)).pack(pady=(0, 8))

        ttk.Separator(left, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 8))

        ttk.Button(left, text="刷新文件列表", command=self._refresh_file_list, **btn_opts).pack(pady=(0, 6))
        ttk.Button(left, text="打开输入文件夹", command=self._open_input_dir, **btn_opts).pack(pady=(0, 6))
        ttk.Button(left, text="打开输出文件夹", command=self._open_output_dir, **btn_opts).pack(pady=(0, 6))
        ttk.Button(left, text="清空日志", command=self._clear_log, **btn_opts).pack(pady=(0, 6))

        # 右侧
        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 文件列表
        file_frame = ttk.LabelFrame(right, text="PDF文件列表", padding=(6, 4))
        file_frame.pack(fill=tk.BOTH, expand=True)

        file_toolbar = ttk.Frame(file_frame)
        file_toolbar.pack(fill=tk.X, pady=(0, 4))
        self.select_all_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            file_toolbar, text="全选/取消全选",
            variable=self.select_all_var,
            command=self._toggle_select_all,
        ).pack(side=tk.LEFT)

        self.file_count_var = tk.StringVar(value="共 0 个文件")
        ttk.Label(file_toolbar, textvariable=self.file_count_var, foreground="gray").pack(side=tk.RIGHT)

        tree_frame = ttk.Frame(file_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("status",)
        self.file_tree = ttk.Treeview(
            tree_frame, columns=columns,
            show="tree headings", selectmode="none", height=8,
        )
        self.file_tree.heading("#0", text="文件名")
        self.file_tree.heading("status", text="状态")
        self.file_tree.column("#0", width=420)
        self.file_tree.column("status", width=120, anchor=tk.CENTER)

        tree_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=tree_scrollbar.set)

        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.file_tree.tag_configure("scanned", foreground="#2563eb")
        self.file_tree.tag_configure("redacted", foreground="#16a34a")

        # 日志区域
        log_frame = ttk.LabelFrame(right, text="处理日志", padding=(6, 4))
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        self.log_text = tk.Text(
            log_frame, height=10, wrap=tk.WORD,
            font=("Menlo", 11), state=tk.DISABLED,
            bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="#d4d4d4",
            relief=tk.FLAT,
            padx=8, pady=6,
        )
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text.tag_configure("info", foreground="#60a5fa")
        self.log_text.tag_configure("warn", foreground="#fbbf24")
        self.log_text.tag_configure("error", foreground="#f87171")
        self.log_text.tag_configure("success", foreground="#4ade80")
        self.log_text.tag_configure("match", foreground="#c084fc")

        # 底部：进度条
        bottom = ttk.Frame(self.root, padding=(12, 4, 12, 10))
        bottom.pack(fill=tk.X)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            bottom, variable=self.progress_var,
            mode="determinate", maximum=100,
        )
        self.progress_bar.pack(fill=tk.X, side=tk.LEFT, expand=True)
        self.progress_label = ttk.Label(bottom, text="", width=18)

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------

    def _log(self, message: str, tag: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{ts}] ", "info")
        self.log_text.insert(tk.END, f"{message}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # 文件列表
    # ------------------------------------------------------------------

    def _refresh_file_list(self):
        self.file_tree.delete(*self.file_tree.get_children())
        self.check_vars.clear()
        self.scan_results.clear()

        pdf_files = sorted(INPUT_DIR.glob("*.pdf"))
        self.file_list = pdf_files

        for f in pdf_files:
            var = tk.BooleanVar(value=True)
            self.check_vars[f.name] = var
            self.file_tree.insert("", tk.END, iid=f.name, text=f"  {f.name}", values=("未扫描",))

        self.select_all_var.set(True)
        self.file_count_var.set(f"共 {len(pdf_files)} 个文件")
        self._log(f"刷新文件列表: 找到 {len(pdf_files)} 个PDF文件")
        self.status_var.set(f"就绪 — {len(pdf_files)} 个文件")

    def _toggle_select_all(self):
        checked = self.select_all_var.get()
        for var in self.check_vars.values():
            var.set(checked)

    def _get_checked_files(self) -> list[Path]:
        return [f for f in self.file_list if self.check_vars.get(f.name, tk.BooleanVar(value=False)).get()]

    # ------------------------------------------------------------------
    # 扫描
    # ------------------------------------------------------------------

    def _scan_selected(self):
        if self.is_processing:
            return

        files = self._get_checked_files()
        if not files:
            messagebox.showinfo("提示", "请先勾选要扫描的PDF文件。")
            return

        self.is_processing = True
        self._disable_buttons()
        self.scan_results.clear()

        known = [n.strip() for n in self.known_name_var.get().split(",") if n.strip()]

        def _run():
            total = len(files)
            for idx, f in enumerate(files):
                self._log(f"开始扫描: {f.name}")
                try:
                    summary = self.desensitizer.scan(f, known)
                    self.scan_results[f.name] = summary

                    n = len(summary.detections)
                    self.root.after(0, lambda fn=f.name, c=n: self._update_tree_status(fn, f"已扫描: {c}处", "scanned"))
                    self._log(f"  扫描完成: 共发现 {n} 处敏感数据", "warn" if n > 0 else "success")

                    type_counts = {}
                    for det in summary.detections:
                        type_counts[det.pattern_type] = type_counts.get(det.pattern_type, 0) + 1
                    for ptype, count in type_counts.items():
                        self._log(f"    [{ptype}] {count} 处", "match")
                except Exception as e:
                    self._log(f"  扫描失败: {e}", "error")
                    self.root.after(0, lambda fn=f.name: self._update_tree_status(fn, "扫描失败", "error"))

                self.progress_var.set((idx + 1) / total * 100)
                self.root.update_idletasks()

            self._finish_processing(f"扫描完成 — {total} 个文件")
            self._log("—" * 40)

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # 脱敏
    # ------------------------------------------------------------------

    def _redact_selected(self):
        if self.is_processing:
            return

        files = self._get_checked_files()
        if not files:
            messagebox.showinfo("提示", "请先勾选要脱敏的PDF文件。")
            return

        ok = messagebox.askokcancel(
            "确认脱敏",
            f"即将对 {len(files)} 个文件执行脱敏操作。\n\n"
            "脱敏将在PDF上添加黑色方块覆盖敏感文本，\n"
            "此操作不可逆，原始文件不会被修改。\n\n"
            "是否继续？"
        )
        if not ok:
            return

        self.is_processing = True
        self._disable_buttons()

        known = [n.strip() for n in self.known_name_var.get().split(",") if n.strip()]

        def _run():
            total = len(files)
            success = 0
            for idx, f in enumerate(files):
                out_path = OUTPUT_DIR / f.name
                self._log(f"开始脱敏: {f.name}")
                try:
                    count = self.desensitizer.redact(f, out_path, known)
                    self.root.after(0, lambda fn=f.name, c=count: self._update_tree_status(fn, f"已脱敏: {c}处", "redacted"))
                    self._log(f"  脱敏完成: 覆盖 {count} 处，保存至 {out_path.name}", "success")
                    success += 1
                except Exception as e:
                    self._log(f"  脱敏失败: {e}", "error")
                    self.root.after(0, lambda fn=f.name: self._update_tree_status(fn, "脱敏失败", "error"))

                self.progress_var.set((idx + 1) / total * 100)
                self.root.update_idletasks()

            self._finish_processing(f"脱敏完成 — 成功 {success}/{total} 个文件")
            self._log("—" * 40)

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _on_progress(self, message: str, fraction: float):
        self.root.after(0, lambda: self.status_var.set(message))
        if message.strip():
            self._log(message)

    def _update_tree_status(self, filename: str, status_text: str, tag: str):
        if self.file_tree.exists(filename):
            self.file_tree.set(filename, "status", status_text)
            self.file_tree.item(filename, tags=(tag,))

    def _disable_buttons(self):
        for child in self.root.winfo_children():
            self._set_children_state(child, tk.DISABLED)

    def _enable_buttons(self):
        for child in self.root.winfo_children():
            self._set_children_state(child, tk.NORMAL)

    def _set_children_state(self, widget, state):
        try:
            if isinstance(widget, (ttk.Button, ttk.Checkbutton)):
                widget.configure(state=state)
            for child in widget.winfo_children():
                self._set_children_state(child, state)
        except tk.TclError:
            pass

    def _finish_processing(self, message: str):
        self.root.after(0, lambda: self._enable_buttons())
        self.root.after(0, lambda: self.status_var.set(message))
        self.root.after(0, lambda: self.progress_var.set(0))
        self.is_processing = False

    def _open_dir(self, path: Path):
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform == "win32":
            os.startfile(str(path))
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _open_input_dir(self):
        self._open_dir(INPUT_DIR)

    def _open_output_dir(self):
        self._open_dir(OUTPUT_DIR)


# ---- 入口 ----

if __name__ == "__main__":
    root = tk.Tk()
    app = DesensitizerApp(root)
    root.mainloop()
