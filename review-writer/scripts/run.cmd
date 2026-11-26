@echo off
setlocal enabledelayedexpansion
set "PY="

if defined WREPORT_PYTHON if exist "%WREPORT_PYTHON%" set "PY=%WREPORT_PYTHON%"

rem 工作台安装包内置的 Python（<app>\runtime\python\python.exe）
if not defined PY if exist "%~dp0..\..\..\runtime\python\python.exe" set "PY=%~dp0..\..\..\runtime\python\python.exe"

if not defined PY (
  for /d %%D in ("%USERPROFILE%\.dsh\dsh-runtimes\*") do (
    if exist "%%D\dependencies\python\python.exe" set "PY=%%D\dependencies\python\python.exe"
  )
)

if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
  echo 没找到 Python 3.10+。安装 Python，或设置 WREPORT_PYTHON 指向 python.exe。
  exit /b 1
)

%PY% -u "%~dp0reviews.py" %*
exit /b %errorlevel%
