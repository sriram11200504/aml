# run_all.ps1 – Start all AML demo services without Docker (SQLite mode)
# Usage: .\run_all.ps1
# Stop with: .\stop_all.ps1

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = "$Root\logs"
$PidDir = "$Root\pids"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $PidDir | Out-Null

function Write-Header {
    Write-Host ""
    Write-Host "+------------------------------------------------------+" -ForegroundColor Cyan
    Write-Host "|           AML Demo - Starting All Services           |" -ForegroundColor Cyan
    Write-Host "+------------------------------------------------------+" -ForegroundColor Cyan
    Write-Host ""
}

function Wait-ForHealth {
    param([string]$Url, [string]$Name, [int]$MaxSeconds = 15)
    Write-Host -NoNewline "  Waiting for $Name"
    $deadline = (Get-Date).AddSeconds($MaxSeconds)
    $client = New-Object System.Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromSeconds(2)
    while ((Get-Date) -lt $deadline) {
        try {
            $task = $client.GetAsync("$Url/health")
            $task.Wait()
            $resp = $task.Result
            if ($resp.IsSuccessStatusCode) {
                Write-Host " [OK]" -ForegroundColor Green
                $client.Dispose()
                return $true
            }
        } catch {
            $dummy = $_
        }
        Start-Sleep -Milliseconds 500
        Write-Host -NoNewline "."
    }
    $client.Dispose()
    Write-Host " [TIMEOUT]" -ForegroundColor Red
    return $false
}

Write-Header

# 1. Start Mock Model Service (Port 8200)
Write-Host "1. Starting Mock Model Service (Port 8200)..." -ForegroundColor Yellow
$modelProc = Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8200" `
    -WorkingDirectory "$Root\aml-platform\mock-model-service" `
    -RedirectStandardOutput "$LogDir\mock-model.log" `
    -RedirectStandardError "$LogDir\mock-model-error.log" `
    -PassThru -WindowStyle Hidden
$modelProc.Id | Set-Content "$PidDir\mock-model.pid"

# 2. Start AML Platform Backend (Port 8100)
Write-Host "2. Starting AML Platform Backend (Port 8100)..." -ForegroundColor Yellow
$amlProc = Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100" `
    -WorkingDirectory "$Root\aml-platform" `
    -RedirectStandardOutput "$LogDir\aml-platform.log" `
    -RedirectStandardError "$LogDir\aml-platform-error.log" `
    -PassThru -WindowStyle Hidden
$amlProc.Id | Set-Content "$PidDir\aml-platform.pid"

# 3. Start Fake Bank Backend (Port 8000)
Write-Host "3. Starting Fake Bank Backend (Port 8000)..." -ForegroundColor Yellow
$bankProc = Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" `
    -WorkingDirectory "$Root\fake-bank" `
    -RedirectStandardOutput "$LogDir\fake-bank.log" `
    -RedirectStandardError "$LogDir\fake-bank-error.log" `
    -PassThru -WindowStyle Hidden
$bankProc.Id | Set-Content "$PidDir\fake-bank.pid"

# Wait for services health checks
Write-Host ""
Write-Host "Checking service health..." -ForegroundColor Yellow
$ok = $true
$ok = $ok -and (Wait-ForHealth "http://127.0.0.1:8200" "Mock Model Service")
$ok = $ok -and (Wait-ForHealth "http://127.0.0.1:8100" "AML Platform API")
$ok = $ok -and (Wait-ForHealth "http://127.0.0.1:8000" "Fake Bank API")

Write-Host ""
Write-Host "+------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "|                  All Services Ready                  |" -ForegroundColor Cyan
Write-Host "+------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "|  Fake Bank App        http://localhost:8000          |"
Write-Host "|  Fake Bank API        http://localhost:8000/docs     |"
Write-Host "|  AML Dashboard        http://localhost:8100/dashboard|"
Write-Host "|  AML Platform API     http://localhost:8100/docs     |"
Write-Host "|  Mock Model Service   http://localhost:8200/docs     |"
Write-Host "+------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "|  Logs: .\logs\                                        |"
Write-Host "|  To stop: .\stop_all.ps1                             |"
Write-Host "+------------------------------------------------------+" -ForegroundColor Cyan
