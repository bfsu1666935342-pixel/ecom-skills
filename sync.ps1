# 技能库同步：提交本地改动 → 拉取远端 → 推送
# 双击「同步.bat」运行。有冲突会停下来提示，不会覆盖你的改动。
$ErrorActionPreference = 'Continue'

function Write-Line {
  param([string]$Text, [string]$Color = 'Gray')
  Write-Host $Text -ForegroundColor $Color
}

function Invoke-Git {
  param([string]$Dir, [string[]]$Arguments)
  Push-Location $Dir
  try {
    $output = (& git @Arguments 2>&1 | Out-String).Trim()
    return [pscustomobject]@{ Code = $LASTEXITCODE; Output = $output }
  } finally {
    Pop-Location
  }
}

$skillsDir = $PSScriptRoot
$workbenchDir = Join-Path (Split-Path $skillsDir -Parent) 'ecom-workbench'
$failed = $false
$report = New-Object System.Collections.ArrayList

Write-Host ''
Write-Line '=== 1/2  技能库 ===' 'Cyan'

# Windows 上 schannel 有时拿不到凭证，统一走 openssl
$tls = Invoke-Git $skillsDir @('config', '--get', 'http.sslBackend')
if (-not $tls.Output) {
  Invoke-Git $skillsDir @('config', 'http.sslBackend', 'openssl') | Out-Null
}

# 新电脑上 git 可能还没配提交身份，没有就补一个（只影响这个仓库）
$who = Invoke-Git $skillsDir @('config', 'user.email')
if (-not $who.Output) {
  Invoke-Git $skillsDir @('config', 'user.name', 'bfsu1666935342-pixel') | Out-Null
  Invoke-Git $skillsDir @('config', 'user.email', 'bfsu1666935342-pixel@users.noreply.github.com') | Out-Null
}

# 把用户名写进远端地址，登录时只需要填 token 这一项
$remote = Invoke-Git $skillsDir @('remote', 'get-url', 'origin')
if ($remote.Output -match '^https://github\.com/') {
  $newUrl = $remote.Output -replace '^https://github\.com/', 'https://bfsu1666935342-pixel@github.com/'
  Invoke-Git $skillsDir @('remote', 'set-url', 'origin', $newUrl) | Out-Null
}

# 有改动就先提交，否则 rebase 会因为工作区不干净而失败
$status = Invoke-Git $skillsDir @('status', '--porcelain')
if ($status.Output) {
  $count = ($status.Output -split "`n").Count
  $machine = $env:COMPUTERNAME
  if (-not $machine) { $machine = 'pc' }
  $msg = 'auto: ' + $machine + ' ' + (Get-Date -Format 'yyyy-MM-dd HH:mm')
  Invoke-Git $skillsDir @('add', '-A') | Out-Null
  $commit = Invoke-Git $skillsDir @('commit', '-m', $msg)
  if ($commit.Code -eq 0) {
    Write-Line ('  已提交 ' + $count + ' 处改动（' + $msg + '）') 'Green'
    [void]$report.Add('提交' + $count)
  } else {
    Write-Line '  提交失败：' 'Red'
    Write-Line $commit.Output 'DarkGray'
    [void]$report.Add('提交失败')
    $failed = $true
  }
} else {
  Write-Line '  没有本地改动' 'DarkGray'
  [void]$report.Add('无改动')
}

# 拉取：把本地提交叠到远端最新之上
if (-not $failed) {
  $pull = Invoke-Git $skillsDir @('pull', '--rebase', '--autostash', 'origin', 'main')
  if ($pull.Code -ne 0) {
    Invoke-Git $skillsDir @('rebase', '--abort') | Out-Null
    Write-Line '  拉取失败——两台电脑可能改了同一个文件。' 'Red'
    Write-Line '  已经退回你的本地版本，东西没丢。把这段截图发我，我来合并。' 'Red'
    Write-Line $pull.Output 'DarkGray'
    [void]$report.Add('拉取失败')
    $failed = $true
  } else {
    Write-Line '  已拉取远端最新' 'Green'
    [void]$report.Add('拉取ok')
  }
}

# 推送
if (-not $failed) {
  Write-Line '  正在上传…' 'DarkGray'
  Write-Line '  （第一次在这台电脑上传，会停在 Password：粘贴 GitHub token 后回车；屏幕上不显示字是正常的）' 'DarkGray'
  # 用 Start-Process 让 git 直接接管控制台，这样登录提示能看见、也能输入
  $proc = Start-Process -FilePath 'git' -ArgumentList @('push', 'origin', 'main') -WorkingDirectory $skillsDir -NoNewWindow -Wait -PassThru
  if ($proc.ExitCode -ne 0) {
    Write-Line '  推送失败。' 'Yellow'
    Write-Line '  如果卡在 Password 那一步输错了，或者这台电脑还没登录 GitHub：' 'Yellow'
    Write-Line '    用户名：bfsu1666935342-pixel（已自动填好）' 'Yellow'
    Write-Line '    密码：GitHub 的 Personal Access Token（不是账号密码）' 'Yellow'
    Write-Line '  登录成功后 Windows 会记住，以后不用再输。' 'Yellow'
    [void]$report.Add('推送失败')
    $failed = $true
  } else {
    Write-Line '  已推送到 GitHub' 'Green'
    [void]$report.Add('推送ok')
  }
}

Write-Host ''
Write-Line '=== 2/2  工作台 ===' 'Cyan'
if (Test-Path $workbenchDir) {
  $wbTls = Invoke-Git $workbenchDir @('config', '--get', 'http.sslBackend')
  if (-not $wbTls.Output) {
    Invoke-Git $workbenchDir @('config', 'http.sslBackend', 'openssl') | Out-Null
  }
  $wb = Invoke-Git $workbenchDir @('pull', '--ff-only', 'origin', 'main')
  if ($wb.Code -eq 0) {
    Write-Line '  已是最新' 'Green'
    [void]$report.Add('工作台最新')
  } else {
    Write-Line '  跳过（本地有改动或无法快进，工作台不动本地文件）' 'DarkGray'
    [void]$report.Add('工作台跳过')
  }
} else {
  Write-Line '  旁边没有 ecom-workbench 文件夹，跳过' 'DarkGray'
  [void]$report.Add('无工作台')
}

# 记一行日志，方便事后确认到底同步没同步
$now = Get-Date
try {
  $logDir = Join-Path $skillsDir 'logs'
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $flag = 'OK  '
  if ($failed) { $flag = 'FAIL' }
  $line = ($now.ToString('yyyy-MM-dd HH:mm:ss')) + '  ' + $flag + '  ' + ($report -join ' / ')
  Add-Content -Path (Join-Path $logDir 'sync.log') -Value $line -Encoding UTF8
} catch {
  # 日志写不进去不影响同步结果
}

Write-Host ''
if ($failed) {
  Write-Line ('✗ 没同步完，见上面的提示（' + $now.ToString('HH:mm:ss') + '）') 'Red'
  exit 1
}
Write-Line ('✓ 同步完成 · ' + ($report -join ' · ') + ' · ' + $now.ToString('HH:mm:ss')) 'Green'
Write-Line '  （这一行就是结果，可以关窗口了）' 'DarkGray'
exit 0
