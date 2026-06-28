@echo off
REM ILX AI CLI launcher
REM Uses the Python venv from ILX AI Workspace — change VENV_PYTHON if yours differs
set VENV_PYTHON=C:\Users\river\Documents\ILX AI Workspace\.venv\Scripts\python.exe
cd /d "%~dp0"
"%VENV_PYTHON%" main.py %*
