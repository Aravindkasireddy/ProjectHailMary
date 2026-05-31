# Launch all components of the Job Search App on Windows
# Run this from PowerShell in the root project folder: .\run_app.ps1

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "   LAUNCHING MAAS JOB SEARCH APP ON WINDOWS" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# Get the directory where this script is located
$ScriptDir = $PSScriptRoot

# 1. Start Python Backend in a new command prompt window
Write-Host "[1/3] Starting Backend API Server (Port 8080)..." -ForegroundColor Green
Start-Process python -ArgumentList "dashboard_server.py" -WorkingDirectory $ScriptDir

# 2. Start Discord Bot in a new command prompt window
Write-Host "[2/3] Starting Discord Bot..." -ForegroundColor Green
Start-Process python -ArgumentList "scripts/discord_bot.py" -WorkingDirectory $ScriptDir

# 3. Start Next.js Frontend in the current PowerShell window
Write-Host "[3/3] Starting Next.js Frontend (Port 3000)..." -ForegroundColor Green
Set-Location -Path "$ScriptDir\dashboard"
npm run dev
