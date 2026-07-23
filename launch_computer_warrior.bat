@echo off
setlocal
cd /d "%~dp0"
py -3 run_computer_warrior.py
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo Computer Warrior exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
