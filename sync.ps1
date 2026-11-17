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

Write-Host ''
Write-Line '=== 1/2  技能库 ===' 'Cyan'

# Windows 上 schannel 有时拿不到凭证，统一走 openssl
$tls = Invoke-Git $skillsDir @('config', '--get', 'http.sslBackend')
if (-not $tls.Output) {
  Invoke-Git $skillsDir @('config', 'http.sslBackend', 'openssl') | Out-Null
}

# 有改动就先提交，否则 rebase 会因为工作区不干净而失败
$status = Invoke-Git $skillsDir @('status', '--porcelain')
if ($status.Output) {
  $count = ($status.Output -split "`n").Count
  $who = $env:COMPUTERNAME
  if (-not $who) { $who = 'pc' }
  $msg = 'auto: ' + $who + ' ' + (Get-Date -Format 'yyyy-MM-dd HH:mm')
  Invoke-Git $skillsDir @('add', '-A') | Out-Null
  $commit = Invoke-Git $skillsDir @('commit', '-m', $msg)
  if ($commit.Code -eq 0) {
    Write-Line ('  已提交 ' + $count + ' 处改动（' + $msg + '）') 'Green'
  } else {
    Write-Line '  提交失败：' 'Red'
    Write-Line $commit.Output 'DarkGray'
    $failed = $true
  }
} else {
  Write-Line '  没有本地改动' 'DarkGray'
}

# 拉取：把本地提交叠到远端最新之上
if (-not $failed) {
  $pull = Invoke-Git $skillsDir @('pull', '--rebase', '--autostash', 'origin', 'main')
  if ($pull.Code -ne 0) {
    Invoke-Git $skillsDir @('rebase', '--abort') | Out-Null
    Write-Line '  拉取失败——两台电脑可能改了同一个文件。' 'Red'
    Write-Line '  已经退回你的本地版本，东西没丢。把这段截图发我，我来合并。' 'Red'
    Write-Line $pull.Output 'DarkGray'
    $failed = $true
  } else {
    Write-Line '  已拉取远端最新' 'Green'
  }
}

# 推送
if (-not $failed) {
  $push = Invoke-Git $skillsDir @('push', 'origin', 'main')
  if ($push.Code -ne 0) {
    Write-Line '  推送失败。' 'Yellow'
    if ($push.Output -match 'could not read Username|Authentication failed|403|terminal prompts disabled') {
      Write-Line '  这台电脑还没登录 GitHub（只需登录一次）：' 'Yellow'
      Write-Line '    用户名：bfsu1666935342-pixel' 'Yellow'
      Write-Line '    密码：GitHub 的 Personal Access Token（不是账号密码）' 'Yellow'
      Write-Line '  Windows 会把凭据记住，以后不用再输。' 'Yellow'
    } else {
      Write-Line $push.Output 'DarkGray'
    }
    $failed = $true
  } else {
    Write-Line '  已推送到 GitHub' 'Green'
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
  } else {
    Write-Line '  跳过（本地有改动或无法快进，工作台不动本地文件）' 'DarkGray'
  }
} else {
  Write-Line '  旁边没有 ecom-workbench 文件夹，跳过' 'DarkGray'
}

Write-Host ''
if ($failed) {
  Write-Line '同步没有全部完成，看上面的红字。' 'Yellow'
  exit 1
}
Write-Line '同步完成，可以开始干活了。' 'Green'
exit 0
