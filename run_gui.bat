@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM ============================================================
REM  원천징수 자동화 GUI 실행 (영문 파일명 — 탐색기에서 찾기 쉬움)
REM  경로: 이 폴더의 run_gui.bat 을 더블클릭
REM  로그: logs\lifecycle.log
REM ============================================================
REM start 로 분리 실행 → 콘솔/에이전트 종료 시 GUI 가 같이 죽지 않음
where pythonw >nul 2>&1
if %ERRORLEVEL%==0 (
  start "WTaxGUI" /D "%~dp0" pythonw.exe gui_main.py
) else (
  where python >nul 2>&1
  if %ERRORLEVEL%==0 (
    start "WTaxGUI" /D "%~dp0" python.exe gui_main.py
  ) else (
    echo Python 을 찾을 수 없습니다. PATH 에 pythonw/python 을 추가하세요.
    pause
    exit /b 1
  )
)
exit /b 0
