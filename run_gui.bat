@echo off
cd /d "%~dp0"
REM Detached GUI launch. Empty start title + pythonw = no extra console.
REM Do NOT use: start "WTaxGUI" python.exe  (that creates a titled black console)

set "PYW="

where pythonw >nul 2>&1
if %ERRORLEVEL%==0 (
  for /f "delims=" %%I in ('where pythonw') do (
    set "PYW=%%I"
    goto :launch
  )
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
  for /f "delims=" %%I in ('where python') do (
    if exist "%%~dpIpythonw.exe" (
      set "PYW=%%~dpIpythonw.exe"
      goto :launch
    )
  )
)

echo Python not found. Add pythonw/python to PATH.
pause
exit /b 1

:launch
start "" /D "%CD%" "%PYW%" gui_main.py
exit /b 0
