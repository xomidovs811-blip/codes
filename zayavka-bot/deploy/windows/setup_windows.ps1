# One-shot installer for Windows (Server or 10/11). Run PowerShell AS ADMINISTRATOR:
#
#   cd C:\path\to\zayavka-bot
#   powershell -ExecutionPolicy Bypass -File deploy\windows\setup_windows.ps1 -Domain 203-0-113-5.sslip.io
#
# -Domain auto : detect this server's public IP and use <ip>.sslip.io automatically.
# -Domain : the https address for the Mini App. With no domain of your own, use
#           <server-public-ip-with-dashes>.sslip.io (free, points to your IP).
#           Ports 80 and 443 must be reachable from the internet.
# Safe to re-run: it updates everything and restarts.
#   ... setup_windows.ps1 -Cloudflare
# -Cloudflare : free Cloudflare quick tunnel (https://xxxx.trycloudflare.com). No domain,
#               router or admin access to other apps needed. The address changes after a
#               restart; tunnel.ps1 updates .env and restarts the bot automatically.
#   ... setup_windows.ps1 -Tailscale
# -Tailscale : publish the Mini App through Tailscale Funnel instead of Caddy:
#              https://<machine>.<tailnet>.ts.net:8443 - no router/port setup needed.
param(
    [string]$Domain = "",
    [switch]$Tailscale,
    [switch]$Cloudflare
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = (Resolve-Path (Join-Path $here "..\..")).Path
Set-Location $AppDir

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Open PowerShell with 'Run as administrator' and run this again." }
if (-not (Test-Path "$AppDir\.env"))       { throw "No .env in $AppDir - copy .env.example to .env and fill it in." }
if (-not (Test-Path "$AppDir\run_bot.py")) { throw "run_bot.py not found in $AppDir - is the deploy folder in the right place?" }

function Write-Step($t) { Write-Host "==> $t" -ForegroundColor Cyan }

# ---------- 1. Stop anything already running (old copies / previous install) ----------
Write-Step "Stopping old copies"
& "$here\manage.ps1" stop | Out-Null

# ---------- 2. Python ----------
Write-Step "Checking Python"
$py = $null
foreach ($cand in @("C:\Program Files\Python312\python.exe", "C:\Program Files\Python313\python.exe", "C:\Program Files\Python311\python.exe")) {
    if (Test-Path $cand) { $py = $cand; break }
}
if (-not $py -and (Get-Command py -ErrorAction SilentlyContinue)) {
    try { $py = (& py -3 -c "import sys;print(sys.executable)").Trim() } catch { $py = $null }
}
if (-not $py) {
    Write-Step "Installing Python 3.12 (all users)"
    $inst = "$env:TEMP\python-3.12.10-amd64.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -OutFile $inst -UseBasicParsing
    Start-Process $inst -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" -Wait
    $py = "C:\Program Files\Python312\python.exe"
    if (-not (Test-Path $py)) { throw "Python install failed." }
}
Write-Host "    Python: $py"

# ---------- 3. Virtualenv + packages ----------
Write-Step "Installing Python packages"
# A .venv copied from another PC points at that PC's Python - rebuild it if broken.
if (Test-Path ".venv\Scripts\python.exe") {
    $ok = $false
    try { & ".venv\Scripts\python.exe" -c "import sys" 2>$null; $ok = ($LASTEXITCODE -eq 0) } catch { $ok = $false }
    if (-not $ok) { Remove-Item -Recurse -Force .venv }
}
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py -m venv .venv }
& ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed." }

# ---------- 4. HTTPS via Caddy ----------
$utf8 = New-Object System.Text.UTF8Encoding($false)   # no BOM - a BOM would break .env
$tasks = @("Zayavka API", "Zayavka Bot")
function Set-WebappUrl($url) {
    $envText = [IO.File]::ReadAllText("$AppDir\.env")
    if ($envText -match '(?m)^WEBAPP_URL=') {
        $envText = $envText -replace '(?m)^WEBAPP_URL=.*$', "WEBAPP_URL=$url"
    } else {
        $envText = $envText.TrimEnd() + "`r`nWEBAPP_URL=$url`r`n"
    }
    [IO.File]::WriteAllText("$AppDir\.env", $envText, $utf8)
}

if ($Tailscale) {
    $Domain = ""
    Write-Step "Publishing via Tailscale Funnel (port 8443 -> 127.0.0.1:8010)"
    $ts = "C:\Program Files\Tailscale\tailscale.exe"
    if (-not (Test-Path $ts)) { throw "Tailscale not found at $ts" }
    Write-Host "    If it prints a login.tailscale.com link, open it, click Enable, and this continues." -ForegroundColor Yellow
    & $ts funnel --bg --https=8443 http://127.0.0.1:8010
    if ($LASTEXITCODE -ne 0) { throw "tailscale funnel failed (see message above)." }
    $dns = ((& $ts status --json | Out-String) | ConvertFrom-Json).Self.DNSName.TrimEnd('.')
    Set-WebappUrl "https://${dns}:8443"
    # Caddy is not used in this mode.
    if (Get-ScheduledTask -TaskName "Zayavka Caddy" -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName "Zayavka Caddy" -Confirm:$false
    }
}
if ($Cloudflare) {
    $Domain = ""
    Write-Step "Setting up Cloudflare quick tunnel -> 127.0.0.1:8010"
    if (-not (Test-Path "$here\cloudflared.exe")) {
        Invoke-WebRequest "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "$here\cloudflared.exe" -UseBasicParsing
    }
    if (Get-ScheduledTask -TaskName "Zayavka Caddy" -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName "Zayavka Caddy" -Confirm:$false
    }
    $tasks = $tasks + @("Zayavka Tunnel")
}
if ($Domain -eq "auto") {
    $ip = (Invoke-RestMethod "https://api.ipify.org" -UseBasicParsing).ToString().Trim()
    $Domain = ($ip -replace '\.', '-') + ".sslip.io"
    Write-Host "    Public IP $ip -> $Domain"
}
if (-not $Domain -and -not $Tailscale -and -not $Cloudflare) {
    Write-Host "    No -Domain given: Mini App pages keep the old WEBAPP_URL from .env" -ForegroundColor Yellow
}
if ($Domain) {
    $Domain = $Domain -replace '^https?://', '' -replace '/.*$', ''
    Write-Step "Setting up HTTPS for $Domain"
    if (-not (Test-Path "$here\caddy.exe")) {
        Invoke-WebRequest "https://caddyserver.com/api/download?os=windows&arch=amd64" -OutFile "$here\caddy.exe" -UseBasicParsing
    }
    [IO.File]::WriteAllText("$here\Caddyfile", "$Domain {`r`n    reverse_proxy 127.0.0.1:8010`r`n}`r`n", $utf8)
    foreach ($p in 80, 443) {
        if (-not (Get-NetFirewallRule -DisplayName "Zayavka HTTPS $p" -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName "Zayavka HTTPS $p" -Direction Inbound -Protocol TCP -LocalPort $p -Action Allow | Out-Null
        }
    }
    Set-WebappUrl "https://$Domain"
    $tasks = @("Zayavka Caddy") + $tasks
}

# ---------- 5. Auto-start tasks (run at boot, even with nobody logged in) ----------
Write-Step "Registering auto-start tasks"
$bats = @{ "Zayavka API" = "run_api.bat"; "Zayavka Bot" = "run_bot.bat"; "Zayavka Caddy" = "run_caddy.bat" }
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
             -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$trigger   = New-ScheduledTaskTrigger -AtStartup
foreach ($t in $tasks) {
    if ($t -eq "Zayavka Tunnel") {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$here\tunnel.ps1`"" -WorkingDirectory $AppDir
    } else {
        $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$here\$($bats[$t])`"" -WorkingDirectory $AppDir
    }
    Register-ScheduledTask -TaskName $t -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
}

# ---------- 6. Start ----------
Write-Step "Starting"
& "$here\manage.ps1" start
Start-Sleep 25
& "$here\manage.ps1" status

$url = ([IO.File]::ReadAllText("$AppDir\.env") | Select-String '(?m)^WEBAPP_URL=(.*)$').Matches[0].Groups[1].Value
Write-Host ""
Write-Host "WEBAPP_URL = $url" -ForegroundColor Green
Write-Host "Test in a browser: $url/table.html   (it should open a page, not an error)"
Write-Host "Logs are in $AppDir\logs"
