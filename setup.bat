@echo off
REM Windows տեղադրում։ Կրկնակի սեղմիր այս ֆայլի վրա կամ գործարկիր PowerShell-ից՝ .\setup.bat
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

echo == Python ստուգում ==
python --version
if errorlevel 1 (
  echo.
  echo [X] Python-ը չի գտնվել։
  echo     Ներբեռնիր https://www.python.org/downloads/ և տեղադրելիս ՊԱՐՏԱԴԻՐ նշիր
  echo     "Add Python to PATH" վանդակը, հետո նորից գործարկիր setup.bat
  pause
  exit /b 1
)

echo == Վիրտուալ միջավայր (.venv) ==
python -m venv .venv
if errorlevel 1 ( echo [X] venv-ը չստեղծվեց & pause & exit /b 1 )

echo == Փաթեթներ ==
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt -q

if not exist .env (
  copy .env.example .env >nul
  echo == Ստեղծվեց .env — բացիր Notepad-ով և դիր թոքենները ==
)

echo == Demo գործարկում (առանց API-ի) ==
.venv\Scripts\python.exe -m src.niche_scan --demo

echo.
echo ============================================================
echo  Պատրաստ է։
echo.
echo  1. Բացիր .env և դիր MPSTATS_TOKEN-ը
echo  2. Ստուգիր՝   mps.bat src.mpstats_client limit
echo  3. Սքան՝      mps.bat src.niche_scan --path "Дом/Кухня" --dry-run
echo  4. Claude Code՝ այս պանակում գրիր  claude
echo ============================================================
pause
