param([switch]$Execute, [switch]$RestoreHistory)
$ErrorActionPreference = 'Stop'
$radarRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if ($radarRoot.TrimEnd('\') -ne 'D:\股票强势监测') { throw '恢复目标不是指定项目' }
$radarChanges = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'changed_files.json') -Raw -Encoding utf8 | ConvertFrom-Json
if (-not $Execute) {
    $radarChanges | Select-Object file, action
    Write-Output '预览：恢复以上源码和实施前快照；新增文件及当前状态另存，不删除事件记录。'
    Write-Output '执行：.\恢复基线.ps1 -Execute；同时回退日线数据库加 -RestoreHistory。'
    return
}
$radarStatus = $null
try { $radarStatus = Invoke-RestMethod 'http://127.0.0.1:8848/__status' -TimeoutSec 5 } catch {}
if ($radarStatus) {
    if ($radarStatus.phase -ne 'ready' -or $radarStatus.scan_active -or $radarStatus.refresh.running) { throw '等待当前扫描与发布结束后再恢复' }
    $radarProc = Get-CimInstance Win32_Process -Filter "ProcessId=$($radarStatus.pid)"
    if ($radarProc.CommandLine -notlike '*D:\股票强势监测\serve.py*') { throw '服务进程身份不符' }
}
$radarStop = Join-Path $radarRoot 'cache\serve.stop'
Set-Content -LiteralPath $radarStop -Value 'radar V1 rollback' -Encoding utf8
if ($radarStatus) { Stop-Process -Id $radarStatus.pid }
$radarStash = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ('rollback_saved_' + (Get-Date -Format yyyyMMdd_HHmmss))))
if (-not $radarStash.StartsWith($PSScriptRoot + '\')) { throw '归档目标不在本轮证据目录' }
New-Item -ItemType Directory -Path $radarStash | Out-Null
foreach ($radarChange in $radarChanges) {
    $radarTarget = [IO.Path]::GetFullPath((Join-Path $radarRoot $radarChange.file))
    if ([IO.Path]::GetDirectoryName($radarTarget) -ne $radarRoot) { throw '源码恢复路径越界' }
    if (Test-Path -LiteralPath $radarTarget) { Copy-Item -LiteralPath $radarTarget -Destination (Join-Path $radarStash $radarChange.file) }
    if ($radarChange.action -eq '修改') {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot ('before\' + $radarChange.file)) -Destination $radarTarget -Force
    } elseif (Test-Path -LiteralPath $radarTarget) {
        Move-Item -LiteralPath $radarTarget -Destination (Join-Path $radarStash ('disabled_' + $radarChange.file))
    }
}
$radarSnapshot = Join-Path $radarRoot 'cache\snapshot.json'
Copy-Item -LiteralPath $radarSnapshot -Destination (Join-Path $radarStash 'snapshot.json')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'before\frozen_snapshot.json') -Destination $radarSnapshot -Force
$radarState = [IO.Path]::GetFullPath((Join-Path $radarRoot 'cache\radar_opportunity_v1'))
if (-not $radarState.StartsWith($radarRoot + '\cache\')) { throw '事件状态路径越界' }
if (Test-Path -LiteralPath $radarState) { Move-Item -LiteralPath $radarState -Destination (Join-Path $radarStash 'radar_opportunity_v1') }
if ($RestoreHistory) {
    foreach ($radarDb in @('market.db','scan_features.db')) {
        $radarDbTarget = Join-Path $radarRoot ('cache\' + $radarDb)
        foreach ($radarSidecar in @('-wal','-shm')) {
            $radarSidecarPath = $radarDbTarget + $radarSidecar
            if (Test-Path -LiteralPath $radarSidecarPath) { Move-Item -LiteralPath $radarSidecarPath -Destination (Join-Path $radarStash ($radarDb + $radarSidecar)) }
        }
        if (Test-Path -LiteralPath $radarDbTarget) { Copy-Item -LiteralPath $radarDbTarget -Destination (Join-Path $radarStash $radarDb) }
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot ('before\' + $radarDb)) -Destination $radarDbTarget -Force
    }
}
Push-Location $radarRoot
try { python -B -X utf8 make_dashboard.py; if ($LASTEXITCODE -ne 0) { throw '旧版看板生成失败，服务保持停止' } } finally { Pop-Location }
Start-Process -FilePath 'D:\_tools\stock-monitor\python\pythonw.exe' -ArgumentList '-B','-X','utf8',(Join-Path $radarRoot 'serve.py'),'--no-browser' -WorkingDirectory $radarRoot -WindowStyle Hidden
Remove-Item -LiteralPath $radarStop
Write-Output ('恢复完成，当前新增内容保存在：' + $radarStash)
