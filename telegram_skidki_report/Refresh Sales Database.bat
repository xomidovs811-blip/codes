<# : ---------- batch part (do not edit) ----------
@echo off
title Refresh Sales Database
echo ============================================
echo   Refresh Sales Database
echo ============================================
echo.
set "SR_DIR=%~dp0"
set "SR_SELF=%~f0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Expression ([System.IO.File]::ReadAllText($env:SR_SELF))"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo DONE. Sales Database refreshed and saved.
    timeout /t 10
) else (
    echo ERROR %RC%. See log: "%~dp0Sales Database refresh log.txt"
    pause
)
exit /b %RC%
: ---------- PowerShell part ---------- #>
# Refresh Sales Database
# Open file -> Enable Editing -> Refresh All -> wait until finished -> Save -> Close
# Exit codes: 0 = OK, 1 = file not found, 2 = file is read-only (open by another user),
#             3 = refresh timeout, 9 = other error
# The Excel this script starts is remembered (PID file). If a run is interrupted
# (window closed, PC hiccup), the next run closes that leftover Excel first,
# so no restart of the PC is needed.

# ===================== SETTINGS =====================
$Folder         = '\\192.168.1.101\Auditor\AUDIT'
$BaseName       = 'Sales Database'      # file name without extension
$TimeoutMinutes = 60
# Optional status message to your private Telegram chat (same bot as the discount report)
$AdminChatFile  = '\\192.168.1.101\Auditor\AUDIT\Скидки\Скидки отчёт\SkidkiReport\state\admin_chat_id.txt'
# ====================================================

$ErrorActionPreference = 'Stop'
$LogFile = Join-Path $env:SR_DIR 'Sales Database refresh log.txt'
$PidFile = Join-Path $env:SR_DIR 'Sales Database refresh excel.pid'

function Write-Log([string]$Message) {
    $line = '{0:yyyy-MM-dd HH:mm:ss}  {1}' -f (Get-Date), $Message
    Write-Host $line
    try { Add-Content -LiteralPath $LogFile -Value $line } catch {}
}

function Send-Status([string]$Text) {
    # never fails the refresh: no chat file / no token / no network -> just skip
    try {
        $token = [Environment]::GetEnvironmentVariable('TELEGRAM_BOT_TOKEN', 'User')
        if (-not $token -or -not (Test-Path -LiteralPath $AdminChatFile)) { return }
        $chat = ([System.IO.File]::ReadAllText($AdminChatFile)).Trim()
        if (-not $chat) { return }
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $body = [System.Text.Encoding]::UTF8.GetBytes((@{ chat_id = $chat; text = $Text } | ConvertTo-Json))
        Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/sendMessage" `
            -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 30 | Out-Null
    } catch {}
}

function Close-LeftoverExcel {
    # Excel started by an earlier run that was interrupted: close it (only that one)
    if (-not (Test-Path -LiteralPath $PidFile)) { return }
    try {
        $old = [int]([System.IO.File]::ReadAllText($PidFile).Trim())
        $p = Get-Process -Id $old -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -eq 'EXCEL' -and $p.StartTime -le (Get-Item -LiteralPath $PidFile).LastWriteTime) {
            Write-Log "Closing Excel left by an interrupted run (PID $old)"
            Stop-Process -Id $old -Force
            Start-Sleep -Seconds 3
        }
    } catch {}
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

function Disable-BackgroundRefresh($wb) {
    foreach ($cn in $wb.Connections) {
        try {
            switch ($cn.Type) {
                1 { $cn.OLEDBConnection.BackgroundQuery = $false }   # OLEDB / Power Query
                2 { $cn.ODBCConnection.BackgroundQuery  = $false }   # ODBC
            }
        } catch {}
    }
    foreach ($ws in $wb.Worksheets) {
        foreach ($qt in $ws.QueryTables) { try { $qt.BackgroundQuery = $false } catch {} }
        foreach ($lo in $ws.ListObjects) {
            try { if ($lo.SourceType -eq 3) { $lo.QueryTable.BackgroundQuery = $false } } catch {}
        }
    }
}

function Test-Refreshing($wb) {
    foreach ($cn in $wb.Connections) {
        try {
            if ($cn.Type -eq 1 -and $cn.OLEDBConnection.Refreshing) { return $true }
            if ($cn.Type -eq 2 -and $cn.ODBCConnection.Refreshing)  { return $true }
        } catch {}
    }
    foreach ($ws in $wb.Worksheets) {
        foreach ($qt in $ws.QueryTables) { try { if ($qt.Refreshing) { return $true } } catch {} }
        foreach ($lo in $ws.ListObjects) {
            try { if ($lo.SourceType -eq 3 -and $lo.QueryTable.Refreshing) { return $true } } catch {}
        }
    }
    return $false
}

# ---------- find the file ----------
$file = Get-ChildItem -LiteralPath $Folder -File |
        Where-Object { $_.BaseName -eq $BaseName -and $_.Extension -match '^\.xls[xmb]?$' } |
        Select-Object -First 1
if (-not $file) {
    Write-Log "ERROR: file '$BaseName.xls*' not found in $Folder"
    exit 1
}
$path = $file.FullName

$excel = $null
$wb    = $null
$rc    = 0
$excelPid = $null
Close-LeftoverExcel
try {
    Write-Log "Starting Excel"
    $before = @(Get-Process EXCEL -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    $excel = New-Object -ComObject Excel.Application
    $excelPid = (Get-Process EXCEL -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } |
                 Select-Object -First 1).Id
    if ($excelPid) { [System.IO.File]::WriteAllText($PidFile, "$excelPid") }
    $excel.Visible          = $false
    $excel.DisplayAlerts    = $false
    $excel.AskToUpdateLinks = $false
    $excel.EnableEvents     = $false

    # ---------- open ----------
    Write-Log "Opening $path"
    $m = [Type]::Missing
    try {
        # Open(FileName, UpdateLinks, ReadOnly, Format, Password, WriteResPassword, IgnoreReadOnlyRecommended)
        $wb = $excel.Workbooks.Open($path, 0, $false, $m, $m, $m, $true)
    } catch {
        Write-Log "Normal open failed: $($_.Exception.Message)"
    }

    # ---------- Enable Editing (Protected View) ----------
    foreach ($pvw in $excel.ProtectedViewWindows) {
        try {
            if ($pvw.Workbook.FullName -ieq $path) {
                Write-Log "Protected View -> Enable Editing"
                $wb = $pvw.Edit()
            }
        } catch {}
    }
    if (-not $wb) { throw "Could not open the file." }

    if ($wb.ReadOnly) {
        Write-Log "ERROR: file opened READ-ONLY (probably open by another user). Nothing saved."
        $hidden = @(Get-Process EXCEL -ErrorAction SilentlyContinue |
                    Where-Object { $_.Id -ne $excelPid -and $_.MainWindowTitle -eq '' })
        if ($hidden.Count -gt 0) {
            Write-Log "Hidden Excel processes on this PC: $($hidden.Count). If nobody else has the file open, close them:"
            Write-Log "  Get-Process EXCEL | Where-Object { `$_.MainWindowTitle -eq '' } | Stop-Process -Force"
        }
        $rc = 2
        throw "read-only"
    }

    # ---------- Refresh All ----------
    Disable-BackgroundRefresh $wb
    Write-Log "Refresh All..."
    $wb.RefreshAll()
    $excel.CalculateUntilAsyncQueriesDone()

    # ---------- wait until finished ----------
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while (Test-Refreshing $wb) {
        if ((Get-Date) -gt $deadline) {
            Write-Log "ERROR: refresh did not finish in $TimeoutMinutes minutes. Nothing saved."
            $rc = 3
            throw "timeout"
        }
        Start-Sleep -Seconds 2
    }

    # refresh pivot tables again so they use the new data
    foreach ($pc in $wb.PivotCaches()) { try { $pc.Refresh() } catch {} }
    $excel.CalculateUntilAsyncQueriesDone()
    Write-Log "Refresh finished"

    # ---------- save and close ----------
    $wb.Save()
    Write-Log "Saved"
    $wb.Close($false)
    $wb = $null
    Write-Log "OK"
}
catch {
    if ($rc -eq 0) {
        $rc = 9
        Write-Log "ERROR: $($_.Exception.Message)"
    }
}
finally {
    if ($wb)    { try { $wb.Close($false) } catch {} }      # never save half-refreshed data
    if ($excel) {
        try { $excel.Quit() } catch {}
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    # Excel sometimes stays in memory after Quit - make sure ours is gone
    if ($excelPid) {
        Start-Sleep -Seconds 2
        Stop-Process -Id $excelPid -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}
$reason = @{ 1 = 'файл не найден'; 2 = 'файл открыт другим пользователем (только чтение)'; 3 = 'обновление не уложилось во время'; 9 = 'ошибка, см. журнал' }
if ($rc -eq 0) { Send-Status "✅ Sales Database обновлена и сохранена" }
else           { Send-Status "❌ Sales Database НЕ обновлена: $($reason[$rc])" }
exit $rc
