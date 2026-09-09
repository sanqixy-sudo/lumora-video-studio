$ErrorActionPreference = 'Stop'
$previewRoot = Split-Path -Parent $PSScriptRoot
$previewPython = Join-Path $previewRoot '.venv/Scripts/python.exe'
$previewRuntime = Join-Path $previewRoot 'runtime'
$previewListeners = @(Get-NetTCPConnection -LocalPort 8101 -State Listen -ErrorAction SilentlyContinue)
if ($previewListeners.Count -gt 0) {
    foreach ($previewListener in $previewListeners) {
        $previewOwner = Get-CimInstance Win32_Process -Filter "ProcessId=$($previewListener.OwningProcess)"
        if ($previewOwner.CommandLine -notmatch 'scripts[\\/]preview_mature\.py') {
            throw 'Port 8101 is used by another program; no process was changed.'
        }
    }
    Write-Output 'Design preview is already running: http://127.0.0.1:8101/design'
    exit 0
}
if (-not (Test-Path -LiteralPath $previewPython -PathType Leaf)) { throw 'Project virtual environment is missing.' }
New-Item -ItemType Directory -Path $previewRuntime -Force | Out-Null
$previewProcess = Start-Process -FilePath $previewPython -ArgumentList @('-B','scripts/preview_mature.py','--serve') -WorkingDirectory $previewRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $previewRuntime 'mature-preview.out.log') -RedirectStandardError (Join-Path $previewRuntime 'mature-preview.err.log') -PassThru
$previewProcess.Id | Set-Content (Join-Path $previewRuntime 'mature-preview.pid')
Write-Output 'Design preview started in the background: http://127.0.0.1:8101/design'
