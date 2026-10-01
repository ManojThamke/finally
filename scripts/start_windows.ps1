# Start FinAlly in Docker. Safe to run repeatedly.
# Usage: .\scripts\start_windows.ps1 [-Build] [-NoOpen]
param(
    [switch]$Build,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

$Image = "finally"
$Container = "finally"
$Volume = "finally-data"
$Port = if ($env:FINALLY_PORT) { $env:FINALLY_PORT } else { "8000" }
$Url = "http://localhost:$Port"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "docker is not installed or not on PATH."
    exit 1
}

docker image inspect $Image *> $null
if ($Build -or $LASTEXITCODE -ne 0) {
    Write-Host "Building Docker image '$Image'..."
    docker build -t $Image .
    if ($LASTEXITCODE -ne 0) { Write-Error "Docker build failed."; exit 1 }
}

# Remove any existing container (running or stopped) so this script is idempotent
docker container inspect $Container *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Removing existing container '$Container'..."
    docker rm -f $Container *> $null
}

$RunArgs = @("run", "-d", "--name", $Container, "-v", "${Volume}:/app/db", "-p", "${Port}:8000")
if (Test-Path (Join-Path $Root ".env")) {
    $RunArgs += @("--env-file", ".env")
} else {
    Write-Warning "No .env file found; AI chat needs OPENROUTER_API_KEY (see .env.example)."
}
$RunArgs += $Image

docker @RunArgs | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to start container."; exit 1 }

Write-Host "Waiting for FinAlly to become healthy..."
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { break }
    } catch { }
    Start-Sleep -Seconds 1
}

Write-Host "FinAlly is running at $Url"
Write-Host "Logs: docker logs -f $Container    Stop: .\scripts\stop_windows.ps1"

if (-not $NoOpen) {
    Start-Process $Url
}
