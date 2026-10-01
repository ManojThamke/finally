# Stop and remove the FinAlly container. The data volume is kept.
$Container = "finally"

docker container inspect $Container *> $null
if ($LASTEXITCODE -eq 0) {
    docker rm -f $Container *> $null
    Write-Host "Stopped FinAlly (data volume 'finally-data' preserved)."
} else {
    Write-Host "FinAlly is not running."
}
