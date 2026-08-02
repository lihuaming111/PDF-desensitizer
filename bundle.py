"""Create output bundle and launcher for Windows portable distribution."""
import os, shutil
from pathlib import Path

ROOT = Path("dist/PDF脱敏工具")
INTERNAL = ROOT / "_internal"

os.makedirs(INTERNAL / "tesseract" / "tessdata", exist_ok=True)
os.makedirs(ROOT / "input", exist_ok=True)
os.makedirs(ROOT / "output", exist_ok=True)

shutil.copy("tesseract/tessdata/chi_sim.traineddata", INTERNAL / "tesseract/tessdata/chi_sim.traineddata")
for f in Path("tesseract/tessdata").glob("*.traineddata"):
    if f.stem in ("eng", "osd"):
        shutil.copy(f, INTERNAL / "tesseract/tessdata/")

LAUNCHER = ROOT / "启动.bat"
LAUNCHER.write_text(
    "@echo off\r\n"
    "chcp 65001 >nul\r\n"
    'cd /d "%~dp0"\r\n'
    'set "TESSDATA_PREFIX=%~dp0_internal\\tesseract\\tessdata"\r\n'
    'set "PATH=%~dp0_internal\\tesseract;%PATH%"\r\n'
    'start "" "%~dp0PDF脱敏工具.exe"\r\n',
    encoding="gbk",
)

print("Bundle done")
