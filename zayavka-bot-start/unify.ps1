# Fixes "two copies of zayavka-bot": compares both folders, lets you pick the
# one to keep, backs up the other copy's database into it, renames the other
# folder so it can't be started by mistake, and makes one Desktop shortcut.
# Nothing is deleted.

$ErrorActionPreference = 'Stop'

$A = 'D:\audit automation\00 Zayavka yozish app\zayavka-bot'
$B = Join-Path ([Environment]::GetFolderPath('Desktop')) 'zayavka-bot'

function Fail($msg) { Write-Host ""; Write-Host "XATO / ERROR: $msg" -ForegroundColor Red; exit 1 }

$folders = @{}
if (Test-Path (Join-Path $A 'run_bot.py')) { $folders['A'] = $A }
if (Test-Path (Join-Path $B 'run_bot.py')) { $folders['B'] = $B }
if ($folders.Count -eq 0) { Fail "No zayavka-bot folder found at:`n  $A`n  $B" }
if ($folders.Count -eq 1) {
    Write-Host "Only one copy exists: $($folders.Values)" -ForegroundColor Green
    Write-Host "Nothing to unify."
    exit 0
}

# --- Stop everything first so the databases aren't being written ---
Write-Host "Stopping running bot / API / tunnel..." -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'run_(bot|api)\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# --- Find a Python to read the databases ---
$py = $null
foreach ($f in $folders.Values) {
    $cand = Join-Path $f '.venv\Scripts\python.exe'
    if (Test-Path $cand) { $py = $cand; break }
}
if (-not $py) {
    if (Get-Command python -ErrorAction SilentlyContinue) { $py = 'python' }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { $py = 'py' }
    else { Fail "Python not found." }
}

$helper = Join-Path $env:TEMP 'zayavka_compare.py'
@'
import sqlite3, sys, json
out = {}
for path in sys.argv[1:]:
    try:
        c = sqlite3.connect("file:" + path + "?mode=ro", uri=True)
        rows = c.execute("select number, created_at from zayavkalar where deleted_at is null").fetchall()
        out[path] = {"count": len(rows),
                     "last": max((r[1] or "" for r in rows), default=""),
                     "numbers": sorted({r[0] for r in rows if r[0]})}
    except Exception as e:
        out[path] = {"error": str(e)}
print(json.dumps(out))
'@ | Set-Content -LiteralPath $helper -Encoding ASCII

$dbA = Join-Path $folders['A'] 'zayavka.db'
$dbB = Join-Path $folders['B'] 'zayavka.db'
$env:PYTHONUTF8 = '1'
$json = & $py $helper $dbA $dbB
$info = $json | ConvertFrom-Json

function Show($key, $path, $db) {
    $d = $info.$db
    $code = Get-ChildItem -LiteralPath (Join-Path $path 'app') -Filter *.py |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    Write-Host ""
    Write-Host "[$key] $path" -ForegroundColor Yellow
    if ($d.error) { Write-Host "    database: cannot read ($($d.error))" }
    else {
        Write-Host "    zayavkas in database : $($d.count)"
        Write-Host "    newest zayavka       : $($d.last)"
    }
    Write-Host "    code last changed    : $($code.LastWriteTime)  ($($code.Name))"
}
Show 'A' $folders['A'] $dbA
Show 'B' $folders['B'] $dbB

$onlyA = @($info.$dbA.numbers | Where-Object { $info.$dbB.numbers -notcontains $_ })
$onlyB = @($info.$dbB.numbers | Where-Object { $info.$dbA.numbers -notcontains $_ })
Write-Host ""
Write-Host "Zayavkas only in A: $($onlyA.Count)  $($onlyA -join ', ')"
Write-Host "Zayavkas only in B: $($onlyB.Count)  $($onlyB -join ', ')"

$suggest = if ($info.$dbA.last -ge $info.$dbB.last) { 'A' } else { 'B' }
Write-Host ""
$choice = (Read-Host "Which copy do you KEEP? Type A or B (Enter = $suggest)").Trim().ToUpper()
if (-not $choice) { $choice = $suggest }
if ($choice -notin @('A', 'B')) { Fail "Please type A or B." }
$other = if ($choice -eq 'A') { 'B' } else { 'A' }
$keep = $folders[$choice]; $old = $folders[$other]

# --- Back up the other copy's database inside the kept folder ---
$stamp = Get-Date -Format 'yyyyMMdd_HHmm'
$oldDb = Join-Path $old 'zayavka.db'
if (Test-Path $oldDb) {
    $dest = Join-Path $keep "zayavka.db.bak_other_copy_$stamp"
    Copy-Item -LiteralPath $oldDb -Destination $dest
    Write-Host "Backed up the other copy's database to: $dest" -ForegroundColor Green
}

# --- Put the start scripts into the kept folder ---
foreach ($f in 'start.bat', 'start.ps1') {
    $src = Join-Path $PSScriptRoot $f
    if ((Test-Path $src) -and ($PSScriptRoot -ne $keep)) { Copy-Item -LiteralPath $src -Destination $keep -Force }
}

# --- Rename the other folder so nobody starts it by mistake ---
$newName = (Split-Path $old -Leaf) + '_OLD_ISHLATMANG'
try {
    Rename-Item -LiteralPath $old -NewName $newName
    Write-Host "Renamed old copy to: $newName" -ForegroundColor Green
} catch {
    Write-Host "Could not rename $old (a window or program is using it). Close it and rename it by hand." -ForegroundColor Yellow
}

# --- One Desktop shortcut ---
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Zayavka bot.lnk'
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = Join-Path $keep 'start.bat'
$s.WorkingDirectory = $keep
$s.Save()

Write-Host ""
Write-Host "TAYYOR / DONE." -ForegroundColor Green
Write-Host "The only bot folder now: $keep"
Write-Host "Start the bot with the 'Zayavka bot' shortcut on your Desktop."
if (($choice -eq 'A' -and $onlyB.Count) -or ($choice -eq 'B' -and $onlyA.Count)) {
    Write-Host ""
    Write-Host "NOTE: the old copy had zayavkas that are not in the kept one (listed above)." -ForegroundColor Yellow
    Write-Host "They are safe in the .bak_other_copy_$stamp file. Ask Claude to merge them if you need them."
}
