# Control the Zayavka bot on Windows. Run PowerShell as administrator:
#   powershell -ExecutionPolicy Bypass -File deploy\windows\manage.ps1 status
#   ... manage.ps1 restart     (after editing .env or code)
#   ... manage.ps1 stop | start
#   ... manage.ps1 logs        (last lines of bot/api logs)
param([ValidateSet("start", "stop", "restart", "status", "logs")][string]$Action = "status")
$ErrorActionPreference = "Continue"

$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = (Resolve-Path (Join-Path $here "..\..")).Path
$names  = @("Zayavka Caddy", "Zayavka API", "Zayavka Bot")

function Stop-All {
    foreach ($n in $names) { Stop-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue }
    # Kill the restart loops together with their python/caddy children.
    Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" |
        Where-Object { $_.CommandLine -match 'run_(api|bot|caddy)\.bat' } |
        ForEach-Object { & taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null }
    # Also any copy started by hand (e.g. "python run_bot.py" from the old setup).
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'run_(api|bot)\.py' } |
        ForEach-Object { & taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null }
}

function Start-All {
    foreach ($n in $names) {
        if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) { Start-ScheduledTask -TaskName $n }
    }
}

switch ($Action) {
    "stop"    { Stop-All; Write-Host "Stopped." }
    "start"   { Start-All; Write-Host "Started." }
    "restart" { Stop-All; Start-Sleep 2; Start-All; Write-Host "Restarted." }
    "logs"    {
        foreach ($f in "bot.log", "api.log", "caddy.log") {
            $p = Join-Path $AppDir "logs\$f"
            if (Test-Path $p) { Write-Host "===== $f" -ForegroundColor Cyan; Get-Content $p -Tail 15 -Encoding UTF8 }
        }
    }
    "status"  {
        foreach ($n in $names) {
            $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
            if ($t) { "{0,-15} {1}" -f $n, $t.State }
        }
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='caddy.exe'" |
                 Where-Object { $_.CommandLine -match 'run_(api|bot)\.py|caddy' }
        Write-Host ("Running processes: " + (($procs | ForEach-Object { if ($_.CommandLine -match 'run_(api|bot)\.py') { $matches[0] } else { 'caddy' } } | Select-Object -Unique) -join ', '))
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:8010/table.html" -UseBasicParsing -TimeoutSec 5
            Write-Host "API check: OK ($($r.StatusCode))" -ForegroundColor Green
        } catch { Write-Host "API check: NOT responding on port 8010" -ForegroundColor Red }
    }
}
