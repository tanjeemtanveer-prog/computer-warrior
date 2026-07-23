@echo off
setlocal
cd /d "%~dp0"
call npm install
if errorlevel 1 exit /b %errorlevel%
call npm run check
if errorlevel 1 exit /b %errorlevel%
call npm test
if errorlevel 1 exit /b %errorlevel%
call npm run db:migrate
exit /b %errorlevel%
