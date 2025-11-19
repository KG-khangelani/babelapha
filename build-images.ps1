# Build and push Docker images for the media pipeline
param(
    [string]$Registry = "localhost:5000",
    [string]$Version = "latest",
    [switch]$Push
)

$ErrorActionPreference = "Stop"

Write-Host "Building pipeline Docker images..." -ForegroundColor Green
Write-Host "Registry: $Registry"
Write-Host "Version: $Version"
Write-Host ""

# Build ClamAV scanner
Write-Host "==> Building clamav scanner..." -ForegroundColor Cyan
Push-Location docker\clamav
Copy-Item ..\utils\pfs_move.py . -Force
docker build -t "${Registry}/clamav:${Version}" -f dockerfile .
Remove-Item pfs_move.py
Write-Host "✓ Built ${Registry}/clamav:${Version}" -ForegroundColor Green

# Build validator
Write-Host "`n==> Building media validator..." -ForegroundColor Cyan
Push-Location ..\validate
Copy-Item ..\utils\pfs_move.py . -Force
docker build -t "${Registry}/validate:${Version}" -f dockerfile .
Remove-Item pfs_move.py
Write-Host "✓ Built ${Registry}/validate:${Version}" -ForegroundColor Green

# Build transcoder
Write-Host "`n==> Building transcoder..." -ForegroundColor Cyan
Push-Location ..\transcode
docker build -t "${Registry}/transcode:${Version}" -f dockerfile .
Write-Host "✓ Built ${Registry}/transcode:${Version}" -ForegroundColor Green

Pop-Location
Pop-Location
Pop-Location

# Push images if requested
if ($Push) {
    Write-Host "`nPushing images to registry..." -ForegroundColor Cyan
    docker push "${Registry}/clamav:${Version}"
    docker push "${Registry}/validate:${Version}"
    docker push "${Registry}/transcode:${Version}"
    Write-Host "✓ All images pushed" -ForegroundColor Green
}

Write-Host "`nBuild complete!" -ForegroundColor Green
Write-Host "Images:"
Write-Host "  - ${Registry}/clamav:${Version}"
Write-Host "  - ${Registry}/validate:${Version}"
Write-Host "  - ${Registry}/transcode:${Version}"
