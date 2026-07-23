@echo off
setlocal
cd /d "%~dp0"

echo Installing the Python dependency required by Computer Warrior...
py -3 -m pip install --upgrade pip
if errorlevel 1 goto :error

rem Force replacement of the incompatible pynput 1.7.7 package.
py -3 -m pip install --upgrade --force-reinstall -r requirements.txt
if errorlevel 1 goto :error

py -3 -c "from importlib.metadata import version; print('Installed pynput', version('pynput'))"
if errorlevel 1 goto :error

echo.
echo Dependencies installed successfully.
echo Computer Warrior requires pynput 1.8.2 or newer for Python 3.13.
pause
exit /b 0

:error
echo.
echo Installation failed. Confirm Python 3 and internet access are available.
pause
exit /b 1
