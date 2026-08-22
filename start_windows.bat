@echo off
setlocal
cd /d %~dp0
if not exist venv\Scripts\python.exe (
  echo Creating virtual environment...
  py -m venv venv
  if errorlevel 1 goto :error
)
call venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if errorlevel 1 goto :error
python verify_project.py
if errorlevel 1 goto :error
python app.py
exit /b 0
:error
echo.
echo Setup failed. Copy the error above.
pause
exit /b 1
