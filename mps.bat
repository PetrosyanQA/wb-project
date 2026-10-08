@echo off
REM Կարճ դյուրանցում Windows-ի համար։
REM Օրինակ՝  mps.bat src.niche_scan --demo
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
.venv\Scripts\python.exe -m %*
