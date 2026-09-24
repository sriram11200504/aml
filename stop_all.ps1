# stop_all.ps1 – Stop all AML demo services

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidDir = "$Root\pids"

Write-Host "Stopping AML demo services..." -ForegroundColor Yellow

$pidFiles = Get-ChildItem -Path $PidDir -Filter "*.pid" -ErrorAction SilentlyContinue

foreach ($f in $pidFiles) {
    $procId = Get-Content $f.FullName
    $name = $f.BaseName
    try {
        $proc = Get-Process -Id $procId -ErrorAction Stop
        Stop-Process -Id $procId -Force
        Write-Host "  Stopped $name (PID $procId)" -ForegroundColor Green
    } catch {
        Write-Host "  $name (PID $procId) was not running" -ForegroundColor Gray
    }
    Remove-Item $f.FullName -ErrorAction SilentlyContinue
}

Write-Host "All services stopped." -ForegroundColor Green
