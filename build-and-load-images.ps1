#!/usr/bin/env pwsh
# Build Docker images on control plane and load into containerd
# Usage: .\build-and-load-images.ps1 [-Version "v1.0"]

param(
    [string]$Version = "latest",
    [string]$ControlPlane = "192.168.10.104",
    [string]$User = "khangelani"
)

Write-Host "=== Building and Loading Pipeline Images ===" -ForegroundColor Cyan
Write-Host "Control Plane: $ControlPlane" -ForegroundColor Yellow
Write-Host "Version: $Version" -ForegroundColor Yellow
Write-Host ""

# Create temporary build directory on control plane
$buildDir = "/tmp/pipeline-build-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Write-Host "[1/5] Creating build directory on control plane..." -ForegroundColor Green
ssh.exe "${User}@${ControlPlane}" "mkdir -p $buildDir"

# Copy necessary files to control plane
Write-Host "[2/5] Copying source files to control plane..." -ForegroundColor Green
scp.exe -r "H:\hikrepos\babelapha\docker\clamav" "${User}@${ControlPlane}:${buildDir}/"
scp.exe -r "H:\hikrepos\babelapha\docker\validate" "${User}@${ControlPlane}:${buildDir}/"
scp.exe -r "H:\hikrepos\babelapha\docker\transcode" "${User}@${ControlPlane}:${buildDir}/"
scp.exe -r "H:\hikrepos\babelapha\docker\utils" "${User}@${ControlPlane}:${buildDir}/"

# Build images on control plane
Write-Host "[3/5] Building images on control plane..." -ForegroundColor Green

# Build clamav image
Write-Host "  Building clamav:${Version}..." -ForegroundColor Cyan
ssh.exe "${User}@${ControlPlane}" @"
cd $buildDir/clamav
cp ../utils/pfs_move.py .
docker build -t clamav:${Version} -f dockerfile .
"@

# Build validate image
Write-Host "  Building validate:${Version}..." -ForegroundColor Cyan
ssh.exe "${User}@${ControlPlane}" @"
cd $buildDir/validate
cp ../utils/pfs_move.py .
docker build -t validate:${Version} -f dockerfile .
"@

# Build transcode image
Write-Host "  Building transcode:${Version}..." -ForegroundColor Cyan
ssh.exe "${User}@${ControlPlane}" @"
cd $buildDir/transcode
docker build -t transcode:${Version} -f dockerfile .
"@

# Import images into containerd
Write-Host "[4/5] Loading images into containerd..." -ForegroundColor Green
ssh.exe "${User}@${ControlPlane}" @"
docker save clamav:${Version} | sudo ctr -n k8s.io images import -
docker save validate:${Version} | sudo ctr -n k8s.io images import -
docker save transcode:${Version} | sudo ctr -n k8s.io images import -
"@

# Clean up
Write-Host "[5/5] Cleaning up..." -ForegroundColor Green
ssh.exe "${User}@${ControlPlane}" "rm -rf $buildDir"
ssh.exe "${User}@${ControlPlane}" "docker image prune -f"

Write-Host ""
Write-Host "=== Build Complete ===" -ForegroundColor Green
Write-Host "Images built and loaded:" -ForegroundColor Yellow
Write-Host "  - clamav:${Version}" -ForegroundColor White
Write-Host "  - validate:${Version}" -ForegroundColor White
Write-Host "  - transcode:${Version}" -ForegroundColor White
Write-Host ""
Write-Host "These images are now available to all pods in the cluster." -ForegroundColor Cyan
Write-Host "Update your DAG to use these image names with imagePullPolicy: Never" -ForegroundColor Cyan
