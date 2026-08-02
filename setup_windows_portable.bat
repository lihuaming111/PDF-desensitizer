@echo off
chcp 65001 >nul
title PDF脱敏工具 — 便携版构建

echo ============================================
echo   PDF脱敏工具 — 便携版构建
echo   在联网 Win10 运行，生成可拷贝的完整包
echo ============================================
echo.

set "ROOT=%~dp0PDF脱敏工具_便携版"
set "PYTHON_DIR=%ROOT%\python"
set "TESSERACT_DIR=%ROOT%\tesseract"
set "DOWNLOADS=%ROOT%\_downloads"

if exist "%ROOT%" (
    echo [警告] %ROOT% 已存在
    choice /c yn /m "删除重建?"
    if errorlevel 2 exit /b
    rmdir /s /q "%ROOT%"
)

mkdir "%ROOT%" "%DOWNLOADS%" "%ROOT%\input" "%ROOT%\output"

:: =====================================================
:: 1. 下载并解压 Python 嵌入式版
:: =====================================================
echo [1/5] 下载 Python 嵌入式版...

set PYTHON_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip

powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%DOWNLOADS%\python-embed.zip'}"

if not exist "%DOWNLOADS%\python-embed.zip" (
    echo [错误] Python 下载失败
    pause & exit /b 1
)

echo   解压中...
powershell -Command "Expand-Archive -Path '%DOWNLOADS%\python-embed.zip' -DestinationPath '%PYTHON_DIR%' -Force"

:: 启用 pip（嵌入式版默认禁用）
echo import site>> "%PYTHON_DIR%\python312._pth"

echo   安装 pip...
cd /d "%PYTHON_DIR%"
python -m ensurepip 2>nul
if errorlevel 1 (
    :: ensurepip 可能不可用，手动下载 get-pip.py
    powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py'"
    python get-pip.py --no-warn-script-location
    del get-pip.py
)

:: =====================================================
:: 2. 安装 Python 依赖
:: =====================================================
echo.
echo [2/5] 安装 Python 依赖包...
python -m pip install pymupdf pytesseract Pillow -q -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
echo   完成

:: =====================================================
:: 3. 下载 Tesseract 便携版
:: =====================================================
echo.
echo [3/5] 下载 Tesseract OCR...

set TESS_URL=https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe
set TESS_PROXY_URL=https://ghproxy.com/%TESS_URL%

echo   尝试直连下载...
powershell -Command "try { Invoke-WebRequest -Uri '%TESS_URL%' -OutFile '%DOWNLOADS%\tesseract.exe' -TimeoutSec 120 } catch { Write-Host '直连失败，尝试代理...' }"
if not exist "%DOWNLOADS%\tesseract.exe" (
    echo   通过代理下载...
    powershell -Command "Invoke-WebRequest -Uri '%TESS_PROXY_URL%' -OutFile '%DOWNLOADS%\tesseract.exe' -TimeoutSec 300"
)

echo   安装 Tesseract 到 %TESSERACT_DIR%...
"%DOWNLOADS%\tesseract.exe" /SILENT /DIR="%TESSERACT_DIR%"

:: 下载中文语言包
echo   下载中文语言包...
mkdir "%TESSERACT_DIR%\tessdata" 2>nul
set TESSDATA_URL=https://github.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata
echo   下载中文语言包...
powershell -Command "try { Invoke-WebRequest -Uri '%TESSDATA_URL%' -OutFile '%TESSERACT_DIR%\tessdata\chi_sim.traineddata' -TimeoutSec 120 } catch {}"
if not exist "%TESSERACT_DIR%\tessdata\chi_sim.traineddata" (
    echo   通过代理下载语言包...
    powershell -Command "Invoke-WebRequest -Uri 'https://ghproxy.com/%TESSDATA_URL%' -OutFile '%TESSERACT_DIR%\tessdata\chi_sim.traineddata' -TimeoutSec 300"
)

:: 只保留中英文，删除其余语言包
for %%f in ("%TESSERACT_DIR%\tessdata\*.traineddata") do (
    if /i not "%%~nxf"=="chi_sim.traineddata" (
        if /i not "%%~nxf"=="eng.traineddata" (
            if /i not "%%~nxf"=="osd.traineddata" (
                del "%%f" 2>nul
            )
        )
    )
)

:: =====================================================
:: 4. 复制项目文件
:: =====================================================
echo.
echo [4/5] 复制项目文件...

for %%f in (main.py desensitizer.py patterns.py requirements.txt) do (
    copy "%~dp0%%f" "%ROOT%\" >nul 2>&1
)

:: =====================================================
:: 5. 创建启动器
:: =====================================================
echo.
echo [5/5] 创建启动器...

(
echo @echo off
echo chcp 65001 ^>nul
echo cd /d "%%~dp0"
echo.
echo set "TESSERACT=%%~dp0tesseract\tesseract.exe"
echo set "TESSDATA_PREFIX=%%~dp0tesseract\tessdata"
echo set "PATH=%%~dp0tesseract;%%~dp0python;%%~dp0python\Scripts;%%PATH%%"
echo.
echo echo 启动 PDF脱敏工具...
echo "%%~dp0python\python.exe" "%%~dp0main.py"
echo if errorlevel 1 pause
) > "%ROOT%\启动.bat"

:: =====================================================
:: 清理
:: =====================================================
rmdir /s /q "%DOWNLOADS%" 2>nul

:: 在代码中设置 tesseract 路径（适配便携版）
echo import os>> "%ROOT%\tesseract_path.py"
echo # 便携版 Tesseract 路径设置>> "%ROOT%\tesseract_path.py"
echo import os as _os, sys as _sys>> "%ROOT%\tesseract_path.py"
echo _dir = _os.path.dirname(_os.path.abspath(__file__))>> "%ROOT%\tesseract_path.py"
echo _tess = _os.path.join(_dir, "tesseract", "tesseract.exe")>> "%ROOT%\tesseract_path.py"
echo if _os.path.exists(_tess):>> "%ROOT%\tesseract_path.py"
echo     import pytesseract>> "%ROOT%\tesseract_path.py"
echo     pytesseract.pytesseract.tesseract_cmd = _tess>> "%ROOT%\tesseract_path.py"
echo     _os.environ.setdefault("TESSDATA_PREFIX", _os.path.join(_dir, "tesseract", "tessdata"))>> "%ROOT%\tesseract_path.py"

echo.
echo ============================================
echo   构建完成!
echo.
echo   位置: %ROOT%
echo   大小: (计算中...)
echo.
echo   将此文件夹复制到离线 Win10
echo   双击 "启动.bat" 即可运行
echo ============================================
echo.

:: 显示大小
powershell -Command "$size = (Get-ChildItem -Path '%ROOT%' -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB; Write-Host \"总大小: $([math]::Round($size, 0)) MB\""

pause
