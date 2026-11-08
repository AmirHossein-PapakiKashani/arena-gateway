# Run from the project you want Gemini CLI to work on.
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$ArenaArguments)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = 'python' }
& $taskPython -X utf8 (Join-Path $PSScriptRoot 'arena_gemini.py') @ArenaArguments
exit $LASTEXITCODE
