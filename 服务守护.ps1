$ErrorActionPreference = 'SilentlyContinue'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 8848
$stopFlag = Join-Path $root 'cache\serve.stop'
$serve = Join-Path $root 'serve.py'
$pythonw = Join-Path $env:USERPROFILE '.workbuddy\binaries\python\versions\3.13.12\pythonw.exe'
$runtimeFile = Join-Path $root 'cache\serve-python.txt'
if (Test-Path -LiteralPath $runtimeFile) {
    $configuredRuntime = (Get-Content -LiteralPath $runtimeFile -Raw).Trim()
    if (Test-Path -LiteralPath $configuredRuntime) { $pythonw = $configuredRuntime }
}

if (-not (Test-Path -LiteralPath $pythonw)) {
    $pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
}
if (-not $pythonw) {
    $pythonw = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}

while ($true) {
    if (-not (Test-Path -LiteralPath $stopFlag)) {
        $alive = $false
        try {
            $resp = Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:$port/__ping" -TimeoutSec 3
            $alive = ($resp.StatusCode -eq 200 -and $resp.Content -match 'pong')
        } catch {
            $alive = $false
        }

        if (-not $alive -and $pythonw) {
            # Read the override on every restart.
            $runtimeFile = Join-Path $root 'cache\serve-python.txt'
            if (Test-Path -LiteralPath $runtimeFile) {
                $configuredRuntime = (Get-Content -LiteralPath $runtimeFile -Raw).Trim()
                if (Test-Path -LiteralPath $configuredRuntime) { $pythonw = $configuredRuntime }
            }
            Start-Process -FilePath $pythonw -WorkingDirectory $root `
                -ArgumentList @($serve, '--no-browser') -WindowStyle Hidden
        }
    }
    Start-Sleep -Seconds 30
}
