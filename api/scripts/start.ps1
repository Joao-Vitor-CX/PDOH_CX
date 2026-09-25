$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location -LiteralPath $projectDirectory
& "$projectDirectory\api\.venv311\Scripts\python.exe" -m uvicorn api.app.main:create_app --factory --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
