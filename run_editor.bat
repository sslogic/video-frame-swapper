@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating local Python environment...
  python -m venv .venv
  if errorlevel 1 goto :error
)

echo Installing/updating editor dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo Starting Movie Frame Quad Editor...
".venv\Scripts\python.exe" movie_quad_editor.py
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo Something failed. Leave this window open and copy the error if you want help debugging it.
pause
exit /b 1
