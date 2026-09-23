# Starts the whole Zayavka bot on Windows with one click:
#   1. Cloudflare tunnel  -> gets a fresh https://....trycloudflare.com address
#   2. writes that address into .env as WEBAPP_URL
#   3. API server (run_api.py) and bot (run_bot.py), each in its own window
# Put this file (and start.bat) inside the zayavka-bot folder, next to run_bot.py.

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'   # fixes garbled Russian names in the logs

function Fail($msg) {
    Write-Host ""
    Write-Host "XATO / ERROR: $msg" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path 'run_bot.py')) { Fail "start.ps1 must be in the zayavka-bot folder (next to run_bot.py)." }
if (-not (Test-Path '.env'))       { Fail ".env file not found in $PSScriptRoot" }
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Fail "cloudflared is not installed or not in PATH. Install it: winget install Cloudflare.cloudflared"
}

# --- Python virtual environment (created once) ---
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host "[1/5] Creating .venv and installing packages (first run only)..." -ForegroundColor Cyan
    python -m venv .venv
    if (-not (Test-Path $py)) { Fail "Could not create .venv. Is Python installed and in PATH?" }
    & $py -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail "pip install failed (see messages above)." }
} else {
    Write-Host "[1/5] .venv found" -ForegroundColor Green
}

# --- Stop old copies: two running bots = Telegram 'Conflict' error ---
Write-Host "[2/5] Stopping old bot / API / tunnel if running..." -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'run_(bot|api)\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# --- Tunnel ---
Write-Host "[3/5] Starting Cloudflare tunnel..." -ForegroundColor Cyan
Remove-Item 'tunnel.log' -ErrorAction SilentlyContinue
Start-Process cloudflared -ArgumentList 'tunnel', '--url', 'http://localhost:8000', '--logfile', 'tunnel.log' `
    -WorkingDirectory $PSScriptRoot -WindowStyle Minimized

$url = $null
for ($i = 0; $i -lt 60 -and -not $url; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path 'tunnel.log') {
        $m = Select-String -Path 'tunnel.log' -Pattern 'https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com' |
            Select-Object -First 1
        if ($m) { $url = $m.Matches[0].Value }
    }
}
if (-not $url) { Fail "The tunnel did not give an address within 60 seconds. Check internet and tunnel.log." }
Write-Host "      Tunnel address: $url" -ForegroundColor Green

# --- Write WEBAPP_URL into .env (UTF-8 without BOM, keeps Cyrillic names intact) ---
Write-Host "[4/5] Updating WEBAPP_URL in .env..." -ForegroundColor Cyan
$envPath = Join-Path $PSScriptRoot '.env'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$text = [IO.File]::ReadAllText($envPath, $utf8)
if ($text -match '(?m)^WEBAPP_URL=') {
    $text = [regex]::Replace($text, '(?m)^WEBAPP_URL=[^\r\n]*', "WEBAPP_URL=$url")
} else {
    if ($text.Length -gt 0 -and -not $text.EndsWith("`n")) { $text += "`r`n" }
    $text += "WEBAPP_URL=$url`r`n"
}
[IO.File]::WriteAllText($envPath, $text, $utf8)

# --- API + bot, each in its own window so you can see errors ---
Write-Host "[5/5] Starting API server and bot..." -ForegroundColor Cyan
Start-Process $py -ArgumentList 'run_api.py' -WorkingDirectory $PSScriptRoot
Start-Sleep -Seconds 4
try {
    Invoke-WebRequest 'http://localhost:8000/' -UseBasicParsing -TimeoutSec 10 | Out-Null
    Write-Host "      API server OK" -ForegroundColor Green
} catch {
    Write-Host "      API server did not answer yet - look at its window for errors." -ForegroundColor Yellow
}
Start-Process $py -ArgumentList 'run_bot.py' -WorkingDirectory $PSScriptRoot

Write-Host ""
Write-Host "TAYYOR / DONE. Wait until the bot window says 'Bot polling started'," -ForegroundColor Green
Write-Host "then send /zayavka in Telegram." -ForegroundColor Green
Write-Host "Keep the bot, API and tunnel windows open. To stop: close them (or run start.bat again to restart)."
