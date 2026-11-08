@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "AIXIAN_PORT=8756"

echo ============================================================
echo   AI 训练工作台 / AI Training Studio v0.1
echo ============================================================

if not "%AIXIAN_SOURCE_MODE%"=="1" (
  if exist "release\AI训练工作台\AI训练工作台.exe" (
    echo [启动] 便携版 exe（内置 Sidecar，无需安装 Python）...
    start "AI 训练工作台" /D "%~dp0release\AI训练工作台" "%~dp0release\AI训练工作台\AI训练工作台.exe"
    pause
    exit /b 0
  )
)

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 Python，请先安装 Python 3.10+ 并加入 PATH。
  pause & exit /b 1
)

if "%AIXIAN_BOOTSTRAP%"=="1" (
  echo [0/3] 安装 Python 依赖...
  python -m pip install -r sidecar\requirements.txt
)

if not exist "desktop\dist\index.html" (
  echo [1/3] 构建桌面前端...
  pushd desktop
  call npm install --ignore-scripts --no-audit --no-fund
  call npm run build
  popd
)

echo [2/3] 启动本地核心服务 http://127.0.0.1:%AIXIAN_PORT%/api/v1 ...
start "AI Xian Sidecar" /D "%~dp0sidecar" python -m aixian --port %AIXIAN_PORT%
timeout /t 3 >nul

echo [3/3] 打开工作台...
if exist "desktop\node_modules\electron\dist\electron.exe" (
  start "AI Xian Desktop" /D "%~dp0desktop" "%~dp0desktop\node_modules\electron\dist\electron.exe" .
) else (
  echo   Electron 二进制未安装，使用浏览器打开（功能一致）。
  start "" http://127.0.0.1:%AIXIAN_PORT%/
)

echo.
echo   旧版 TrainFlow 原型不属于本仓库，如需迁移旧数据请用 aixian.migration --legacy-root 指定目录。
echo   设置 AIXIAN_BOOTSTRAP=1 可在启动时自动安装 Python 依赖。
echo   设置 AIXIAN_SOURCE_MODE=1 可跳过 exe，强制从源码运行。
echo.
pause
