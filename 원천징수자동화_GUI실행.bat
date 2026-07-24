@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM pythonw = 콘솔 창 없음. (python.exe 콘솔을 닫으면 GUI 도 같이 종료됨)
where pythonw >nul 2>&1
if %ERRORLEVEL%==0 (
  start "" pythonw gui_main.py
) else (
  start "" pythonw.exe gui_main.py
)
exit /b 0
