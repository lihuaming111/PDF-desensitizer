#!/usr/bin/env python3
"""PDF脱敏工具 — 独立打包脚本（macOS / Windows）"""

import sys
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).parent
DIST = BASE / "dist"
BUILD = BASE / "build_output"
APP_NAME = "PDF脱敏工具"


def install_pyinstaller():
    print("[1/4] 安装 PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def clean():
    print("[2/4] 清理旧构建...")
    for d in [DIST, BUILD]:
        if d.exists():
            shutil.rmtree(d)
    for f in BASE.glob("*.spec"):
        f.unlink()
    shutil.rmtree(BASE / "__pycache__", ignore_errors=True)


def find_tesseract():
    """查找本机 Tesseract 路径和 tessdata 目录。"""
    paths = [
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for p in paths:
        if Path(p).exists():
            tess = Path(p)
            tessdata = tess.parent.parent / "share" / "tessdata"
            if not tessdata.exists():
                tessdata = tess.parent / "tessdata"
            return tess, tessdata
    # fallback: which
    result = shutil.which("tesseract")
    if result:
        tess = Path(result)
        tessdata = tess.parent.parent / "share" / "tessdata"
        if not tessdata.exists():
            tessdata = tess.parent / "tessdata"
        return tess, tessdata
    return None, None


def build_mac():
    tess, tessdata = find_tesseract()
    if not tess:
        print("❌ 未找到 Tesseract OCR，请先运行: brew install tesseract tesseract-lang")
        sys.exit(1)

    print(f"  使用 Tesseract: {tess}")
    print(f"  使用 tessdata:  {tessdata}")

    print("[3/4] PyInstaller 打包...")

    sep = ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--windowed",
        f"--name={APP_NAME}",
        f"--distpath={DIST}",
        f"--workpath={BUILD}",
        "--noconfirm", "--clean",
        "--add-data", f"patterns.py{sep}.",
        "--add-data", f"desensitizer.py{sep}.",
        "--add-data", f"config.json{sep}.",
        "--add-binary", f"{tess}{sep}tesseract/",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "pytesseract",
        "--hidden-import", "fitz",
        "--hidden-import", "tkinter",
        "main.py",
    ]
    subprocess.check_call(cmd, cwd=str(BASE))

    # 复制 tessdata 到 bundle
    bundle_dir = DIST / APP_NAME / "_internal"
    if tessdata.exists():
        dst = bundle_dir / "tesseract" / "tessdata"
        dst.mkdir(parents=True, exist_ok=True)
        for f in tessdata.glob("*.traineddata"):
            if f.stem in ("chi_sim", "chi_tra", "eng", "osd"):
                shutil.copy2(f, dst / f.name)
        print(f"  语言包已复制 (chi_sim, eng)")

    # 复制 config.json 到便于编辑的位置
    shutil.copy(BASE / "config.json", DIST / APP_NAME / "config.json")
    shutil.copy(BASE / "config.json", bundle_dir / "config.json")

    # 创建 input/output 目录
    (DIST / APP_NAME / "input").mkdir(parents=True, exist_ok=True)
    (DIST / APP_NAME / "output").mkdir(parents=True, exist_ok=True)

    # 创建启动脚本
    launcher = DIST / APP_NAME / "启动.sh"
    launcher.write_text(
        "#!/bin/bash\n"
        'cd "$(dirname "$0")"\n'
        'export TESSDATA_PREFIX="$(pwd)/_internal/tesseract/tessdata"\n'
        'export PATH="$(pwd)/_internal/tesseract:$PATH"\n'
        '"./PDF脱敏工具"\n'
    )
    launcher.chmod(0o755)

    print(f"[4/4] 打包完成")
    print_size()


def build_windows():
    """Windows 用便携式部署（不依赖 PyInstaller）。"""
    print("[3/4] 准备 Windows 便携版...")

    out = DIST / APP_NAME
    out.mkdir(parents=True, exist_ok=True)

    # 复制项目文件
    for f in ["main.py", "desensitizer.py", "patterns.py", "requirements.txt"]:
        shutil.copy2(BASE / f, out / f)

    # 创建 input/output
    (out / "input").mkdir(parents=True, exist_ok=True)
    (out / "output").mkdir(parents=True, exist_ok=True)

    # 创建启动脚本（需要先运行 setup_windows_portable.bat 安装依赖）
    launcher = out / "启动.bat"
    launcher.write_text(
        "@echo off\nchcp 65001 >nul\n"
        "set TESSERACT=%~dp0tesseract\\tesseract.exe\n"
        "set TESSDATA_PREFIX=%~dp0tesseract\\tessdata\n"
        'set "PATH=%~dp0tesseract;%~dp0python;%~dp0python\\Scripts;%PATH%"\n'
        '"%~dp0python\\python.exe" "%~dp0main.py"\n'
    )

    print(f"  Windows 源文件已准备: {out}")
    print(f"  将此文件夹 + setup_windows_portable.bat 复制到 Win10")
    print(f"  先在联网 Win10 上运行 setup_windows_portable.bat")
    print(f"  然后将整个文件夹复制到离线 Win10，双击 启动.bat")


def print_size():
    size_mb = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"\n  ✅ 输出: {DIST / APP_NAME}")
    print(f"  📦 大小: {size_mb:.0f}MB")


def main():
    print(f"=== {APP_NAME} 打包工具 ===\n")

    install_pyinstaller()
    clean()

    if sys.platform == "darwin":
        build_mac()
    elif sys.platform == "win32":
        build_windows()
    else:
        print(f"不支持的系统: {sys.platform}")
        sys.exit(1)


if __name__ == "__main__":
    main()
