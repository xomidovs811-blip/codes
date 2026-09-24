# Keeps a free Cloudflare quick tunnel (https://xxxx.trycloudflare.com -> 127.0.0.1:8010) running.
# The address changes every time cloudflared starts, so each time it:
#   1. writes the new address into .env as WEBAPP_URL
#   2. restarts the bot process (the run_bot.bat loop starts it again within seconds),
#      and the bot re-points all its Mini App buttons to the new address on startup.
$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = (Resolve-Path (Join-Path $here "..\..")).Path
$cf     = Join-Path $here "cloudflared.exe"
$logDir = Join-Path $AppDir "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$utf8   = New-Object System.Text.UTF8Encoding($false)

function Read-Shared($path) {
    # cloudflared keeps the file open - read it without locking.
    try {
        $fs = [IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
        $sr = New-Object IO.StreamReader($fs)
        $t = $sr.ReadToEnd(); $sr.Close(); return $t
    } catch { return "" }
}

while ($true) {
    $cur = Join-Path $logDir "tunnel_current.log"
    Remove-Item $cur, "$cur.out" -ErrorAction SilentlyContinue
    $p = Start-Process $cf -ArgumentList "tunnel --no-autoupdate --url http://127.0.0.1:8010" `
         -RedirectStandardError $cur -RedirectStandardOutput "$cur.out" -PassThru -WindowStyle Hidden

    $url = $null
    for ($i = 0; $i -lt 90 -and -not $p.HasExited; $i++) {
        Start-Sleep 1
        $m = [regex]::Match((Read-Shared $cur), 'https://[a-z0-9-]+\.trycloudflare\.com')
        if ($m.Success) { $url = $m.Value; break }
    }

    if ($url) {
        Add-Content (Join-Path $logDir "tunnel.log") "$(Get-Date -Format s) new address $url"
        $envPath = Join-Path $AppDir ".env"
        $envText = [IO.File]::ReadAllText($envPath)
        if ($envText -match '(?m)^WEBAPP_URL=') {
            $envText = $envText -replace '(?m)^WEBAPP_URL=.*$', "WEBAPP_URL=$url"
        } else {
            $envText = $envText.TrimEnd() + "`r`nWEBAPP_URL=$url`r`n"
        }
        [IO.File]::WriteAllText($envPath, $envText, $utf8)
        Start-Sleep 5   # let the new hostname become reachable
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -match 'run_bot\.py' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    } else {
        Add-Content (Join-Path $logDir "tunnel.log") "$(Get-Date -Format s) could not get an address: $(Read-Shared $cur)"
    }

    if (-not $p.HasExited) { $p.WaitForExit() }
    Start-Sleep 5
}
