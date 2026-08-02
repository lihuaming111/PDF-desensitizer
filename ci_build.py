"""CI build script for Windows — download deps, build exe, create zip."""

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

TESS_URL = "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe"
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata"

# Step 1: Install pip deps
print("[1/4] Installing pip packages...")
subprocess.run(["pip", "install", "pyinstaller", "pymupdf", "pytesseract", "Pillow", "-q"], check=True)

# Step 2: Download and extract Tesseract
print("[2/4] Downloading Tesseract...")
urllib.request.urlretrieve(TESS_URL, "tesseract.zip")
subprocess.run(["7z", "x", "tesseract.zip", "-otesseract", "-y"], check=True)
os.makedirs("tesseract/tessdata", exist_ok=True)
urllib.request.urlretrieve(TESSDATA_URL, "tesseract/tessdata/chi_sim.traineddata")

# Step 3: PyInstaller build
print("[3/4] Building exe...")
subprocess.run([
    "pyinstaller",
    "--onedir", "--windowed",
    "--name=PDF脱敏工具",
    "--distpath=dist",
    "--workpath=build_output",
    "--noconfirm", "--clean",
    "--add-data=patterns.py;.",
    "--add-data=desensitizer.py;.",
    "--add-binary=tesseract/tesseract.exe;tesseract/",
    "--hidden-import=PIL",
    "--hidden-import=PIL.Image",
    "--hidden-import=pytesseract",
    "--hidden-import=fitz",
    "--hidden-import=tkinter",
    "main.py",
], check=True)

# Step 4: Bundle tessdata, DLLs, create launcher, zip
print("[4/4] Bundling...")
ROOT = Path("dist/PDF脱敏工具")
INTERNAL = ROOT / "_internal"

os.makedirs(INTERNAL / "tesseract" / "tessdata", exist_ok=True)
os.makedirs(ROOT / "input", exist_ok=True)
os.makedirs(ROOT / "output", exist_ok=True)

# Copy all tesseract files (exe + DLLs) into the bundle
for f in Path("tesseract").iterdir():
    if f.is_file():
        shutil.copy2(f, INTERNAL / "tesseract" / f.name)

shutil.copy("tesseract/tessdata/chi_sim.traineddata", INTERNAL / "tesseract/tessdata/chi_sim.traineddata")
for f in Path("tesseract/tessdata").glob("*.traineddata"):
    if f.stem in ("eng", "osd"):
        shutil.copy(f, INTERNAL / "tesseract/tessdata/")

launcher = ROOT / "启动.bat"
launcher.write_text(
    "@echo off\r\n"
    "chcp 65001 >nul\r\n"
    'cd /d "%~dp0"\r\n'
    r'set "TESSDATA_PREFIX=%~sdp0_internal\tesseract\tessdata"' + "\r\n"
    r'set "PATH=%~sdp0_internal\tesseract;%PATH%"' + "\r\n"
    'start "" "%~dp0PDF脱敏工具.exe"\r\n',
    encoding="gbk",
)

subprocess.run(["powershell", "Compress-Archive", "-Path", r"dist\PDF脱敏工具\*", "-DestinationPath", "PDF脱敏工具_Windows.zip"], check=True)

print("Done!")
