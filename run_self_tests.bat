@echo off
setlocal
cd /d "%~dp0"
py -3 self_test.py
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo All Computer Warrior self-tests passed.
) else (
  echo One or more self-tests failed. Read QA_NOTES.md.
)
pause
exit /b %EXIT_CODE%
