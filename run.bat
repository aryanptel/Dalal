@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
echo Starting Dalal AI...
python -m dalal_ai
pause
