$ErrorActionPreference = "Stop"

# 找一个能用的 Python 3.10+：环境变量 > PATH > py 启动器 > DSH 自带运行时
$candidates = @()
if ($env:WREPORT_PYTHON) { $candidates += $env:WREPORT_PYTHON }
$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd) { $candidates += $cmd.Source }
$dsh = Join-Path $env:USERPROFILE ".dsh\dsh-runtimes"
if (Test-Path $dsh) {
    $candidates += Get-ChildItem $dsh -Recurse -Filter python.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*dependencies\python\python.exe" } |
        Select-Object -ExpandProperty FullName
}

$python = $null
foreach ($candidate in $candidates) {
    if (-not $candidate -or -not (Test-Path $candidate)) { continue }
    & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
}

if (-not $python) {
    Write-Host "没找到 Python 3.10+。装一个 Python，或设置 WREPORT_PYTHON 指向 python.exe。" -ForegroundColor Red
    exit 1
}

& $python (Join-Path $PSScriptRoot "wreport.py") @args
exit $LASTEXITCODE
