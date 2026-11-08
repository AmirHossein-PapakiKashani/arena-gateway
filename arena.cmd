@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -X utf8 "%~dp0arena_gemini.py" %*
) else (
  python -X utf8 "%~dp0arena_gemini.py" %*
)
exit /b %errorlevel%
