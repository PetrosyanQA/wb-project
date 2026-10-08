@echo off
chcp 65001 >nul
REM Запуск Claude Code с Telegram-каналом в папке проекта.
REM Токен бота хранится в %USERPROFILE%\.claude\channels\telegram\.env, НЕ здесь.
cd /d "%~dp0"
REM Пути установки claude (winget) и bun — на случай, если PATH окна ещё не обновился.
set "PATH=%USERPROFILE%\.bun\bin;%LOCALAPPDATA%\Microsoft\WinGet\Packages\Anthropic.ClaudeCode_Microsoft.Winget.Source_8wekyb3d8bbwe;%PATH%"

where claude >nul 2>&1 || (echo [!] Claude Code CLI не найден. Установите: winget install Anthropic.ClaudeCode & pause & exit /b 1)
where bun >nul 2>&1 || (echo [!] Bun не найден. Установите: powershell -c "irm bun.sh/install.ps1 ^| iex" & pause & exit /b 1)
if not exist "%USERPROFILE%\.claude\channels\telegram\.env" (
  echo [!] Нет файла с токеном бота: %USERPROFILE%\.claude\channels\telegram\.env
  echo     Создайте его со строкой TELEGRAM_BOT_TOKEN=... ^(токен от @BotFather^)
  pause & exit /b 1
)

claude --channels plugin:telegram@claude-plugins-official
pause
