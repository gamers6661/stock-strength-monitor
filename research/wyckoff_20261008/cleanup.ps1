$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$candidates = @(
    'research\attack_20260930\before',
    'research\attack_funds_20260930\before',
    'research\consolidation_phase_20260930\before',
    'research\intraday_path_20260930\before',
    'research\trend_consolidation_20260930\before',
    'research\consolidation_audit_20260930\after',
    'research\consolidation_ma10_20260930\after',
    'research\consolidation_ma20_20261008\after',
    'research\consolidation_phase_20260930\after',
    'research\intraday_path_20260930\after',
    'research\trend_consolidation_20260930\after',
    'research\trend_strict_20260930\after',
    'research\dual_axis_20260923\backup',
    'research\ma_trend_20260923\backup',
    'research\simple_strength_20260923\backup',
    'research\stock_strength_20260924\backup',
    'research\price_basis_20260929\baseline',
    'cache\pre_intraday_20260928',
    'cache\stock_strength_daily\v2',
    'cache\close_strong',
    'dashboard_template.black.bak.html'
)
$records = @()
foreach ($relative in $candidates) {
    $candidate = Join-Path $taskRoot $relative
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    if (-not $resolved.StartsWith($taskRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "清理对象超出项目范围：$resolved"
    }
    $entry = Get-Item -LiteralPath $resolved
    if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '禁止清理链接目标' }
    $files = @(if ($entry.PSIsContainer) { Get-ChildItem -LiteralPath $resolved -File -Recurse } else { $entry })
    $records += [pscustomobject]@{path=$relative;files=$files.Count;bytes=($files | Measure-Object Length -Sum).Sum;resolved=$resolved}
}
$manifest = [ordered]@{
    reviewed_at=(Get-Date).ToString('yyyy-MM-dd HH:mm:ss');
    reason='删除未被运行入口或研究对照加载的重复源码、过期缓存和旧模板';
    retained_backup='backups/latest_before_wyckoff_round1';
    protected='现行v6评分/收盘缓存、行情数据库、逐日报价/事件留档、同花顺分类、研究脚本实际读取的冻结源码和输入';
    deleted=$records
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'cleanup_manifest.json') -Encoding utf8
foreach ($record in $records) {
    Remove-Item -LiteralPath $record.resolved -Recurse -Force
}
[pscustomobject]@{deleted_targets=$records.Count;deleted_files=($records | Measure-Object files -Sum).Sum;deleted_bytes=($records | Measure-Object bytes -Sum).Sum} | ConvertTo-Json
