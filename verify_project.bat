@echo off
setlocal
py -3 self_test.py
if errorlevel 1 exit /b 1
pushd cloudflare
npm test
set result=%errorlevel%
popd
exit /b %result%
