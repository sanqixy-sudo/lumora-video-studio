param(
    [string]$ImageName = "sora-wuyin-omni",
    [string]$Version = "20260806",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"

if (-not $OutputDirectory) {
    $OutputDirectory = (Get-Location).Path
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
}

$imageTag = "${ImageName}:${Version}"
$safeImageName = $ImageName.Replace("/", "-").Replace(":", "-")
$packagePath = Join-Path $OutputDirectory "${safeImageName}-${Version}.tar"
$checksumPath = "${packagePath}.sha256"

docker version | Out-Host
docker build --tag $imageTag .
docker run --rm --entrypoint python $imageTag -m unittest discover -s tests -v
docker save --output $packagePath $imageTag

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $packagePath).Hash.ToLowerInvariant()
$packageName = Split-Path -Leaf $packagePath
Set-Content -Encoding ascii -NoNewline -LiteralPath $checksumPath -Value "${hash}  ${packageName}`n"

Write-Host "Image: $imageTag"
Write-Host "Package: $packagePath"
Write-Host "SHA-256: $hash"
