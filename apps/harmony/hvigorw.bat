@echo off
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%hvigor\hvigor-wrapper.js" (
  node "%ROOT%hvigor\hvigor-wrapper.js" %*
  exit /b %ERRORLEVEL%
)
if defined DEVECO_HOME if exist "%DEVECO_HOME%\tools\hvigor\bin\hvigorw.bat" (
  call "%DEVECO_HOME%\tools\hvigor\bin\hvigorw.bat" %*
  exit /b %ERRORLEVEL%
)
echo 未找到 hvigor。请用 DevEco Studio 26.0.0 Release 打开本工程，或设置 DEVECO_HOME。
exit /b 1
