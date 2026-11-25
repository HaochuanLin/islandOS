<#
.SYNOPSIS
Start the local IslandOS reference API and the React Customer Console.

.DESCRIPTION
Starts two loopback processes and records their PIDs so they can be stopped
together:

  * islandos_service_api.py on 127.0.0.1:<ApiPort>, using <Database>
  * "npm run dev" (Vite) on 127.0.0.1:<ConsolePort>, proxying /api to the API

Registration stays disabled unless -BootstrapRegistration is passed, which is
only for creating the first owner tenant. Both services bind loopback only: do
not treat this script as a deployment.

.PARAMETER ApiPort
API port. Default 8766.

.PARAMETER ConsolePort
Vite dev-server port. Default 5173; must match frontend/vite.config.ts.

.PARAMETER Database
SQLite file passed to --database, relative to the repository root.
Default build/islandos-service.sqlite3.

.PARAMETER BootstrapRegistration
Pass --allow-registration to the API. Stop and restart without it afterwards.

.PARAMETER Stop
Stop the processes recorded by the last successful start, then exit.

.EXAMPLE
.\scripts\start_console.ps1

.EXAMPLE
.\scripts\start_console.ps1 -BootstrapRegistration
#>
param(
    [int]$ApiPort = 8766,
    [int]$ConsolePort = 5173,
    [string]$Database = "build/islandos-service.sqlite3",
    [switch]$BootstrapRegistration,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $repoRoot "build\logs"
$pidFile = Join-Path $runDir "console-processes.json"
$apiOut = Join-Path $runDir "api.out.log"
$apiErr = Join-Path $runDir "api.err.log"
$webOut = Join-Path $runDir "console.out.log"
$webErr = Join-Path $runDir "console.err.log"

if (-not (Test-Path $runDir)) {
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null
}

function Test-PortListening([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Stop-RecordedProcess([int]$ProcessId, [string]$Pattern) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $false }
    if ($process.CommandLine -notmatch $Pattern) { return $false }
    # npm.cmd stays alive while its node/vite child serves the console, so stop
    # the whole tree; a single Stop-Process would leave the port bound.
    & taskkill.exe /PID $ProcessId /T /F | Out-Null
    return ($LASTEXITCODE -eq 0)
}

if ($Stop) {
    if (-not (Test-Path $pidFile)) {
        Write-Output "No recorded console processes; nothing to stop."
        exit 0
    }
    $record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
    $stopped = @()
    if (Stop-RecordedProcess -ProcessId ([int]$record.api_pid) -Pattern "islandos_service_api.py") {
        $stopped += "api $($record.api_pid)"
    }
    if (Stop-RecordedProcess -ProcessId ([int]$record.console_pid) -Pattern "npm|node") {
        $stopped += "console $($record.console_pid)"
    }
    Remove-Item -LiteralPath $pidFile -Force
    if ($stopped.Count -eq 0) {
        Write-Output "Recorded processes had already exited."
    } else {
        Write-Output ("Stopped: " + ($stopped -join ", "))
    }
    exit 0
}

foreach ($port in @($ApiPort, $ConsolePort)) {
    if (Test-PortListening $port) {
        throw "Port $port is already in use. Stop the other service or pass a different port (see -Stop, -ApiPort, -ConsolePort)."
    }
}

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($null -eq $npm) { throw "npm.cmd was not found on PATH." }
if (-not (Test-Path (Join-Path $repoRoot "frontend\node_modules"))) {
    throw "frontend\node_modules is missing. Run 'npm install' in frontend first."
}

$apiArgs = @(
    "islandos_service_api.py",
    "--host", "127.0.0.1",
    "--port", "$ApiPort",
    "--database", $Database
)
if ($BootstrapRegistration) { $apiArgs += "--allow-registration" }

$apiProcess = Start-Process -FilePath $python -ArgumentList $apiArgs -WorkingDirectory $repoRoot `
    -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr -WindowStyle Hidden -PassThru

$healthUrl = "http://127.0.0.1:$ApiPort/api/v1/health"
$healthy = $false
for ($attempt = 1; $attempt -le 40; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -eq 200) { $healthy = $true; break }
    } catch {
        if ($apiProcess.HasExited) { break }
    }
}

if (-not $healthy) {
    Stop-Process -Id $apiProcess.Id -Force -ErrorAction SilentlyContinue
    $tail = ""
    if (Test-Path $apiErr) { $tail = (Get-Content -LiteralPath $apiErr -Tail 8) -join "`n" }
    throw "The reference API did not answer $healthUrl. stderr tail:`n$tail"
}

$env:ISLANDOS_API_TARGET = "http://127.0.0.1:$ApiPort"
$consoleProcess = Start-Process -FilePath $npm.Source -ArgumentList "run", "dev", "--", "--port", "$ConsolePort" `
    -WorkingDirectory (Join-Path $repoRoot "frontend") `
    -RedirectStandardOutput $webOut -RedirectStandardError $webErr -WindowStyle Hidden -PassThru
Remove-Item Env:ISLANDOS_API_TARGET -ErrorAction SilentlyContinue

$record = [ordered]@{
    started_at = (Get-Date).ToString("o")
    api_port = $ApiPort
    console_port = $ConsolePort
    database = $Database
    registration_open = [bool]$BootstrapRegistration
    api_pid = $apiProcess.Id
    console_pid = $consoleProcess.Id
}
$record | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding utf8

Write-Output "IslandOS local console started."
Write-Output "  API      http://127.0.0.1:$ApiPort/api/v1/health (pid $($apiProcess.Id))"
Write-Output "  Console  http://127.0.0.1:$ConsolePort/ (pid $($consoleProcess.Id))"
Write-Output "  Database $Database"
Write-Output "  Logs     build\logs\api.*.log, build\logs\console.*.log"
if ($BootstrapRegistration) {
    Write-Output "  Registration is OPEN for first-owner bootstrap. Stop it with -Stop and restart without -BootstrapRegistration."
}
Write-Output "Stop both with: .\scripts\start_console.ps1 -Stop"
