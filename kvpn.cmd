@echo off
setlocal
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 "%~dp0kvpn" %*
) else (
    python "%~dp0kvpn" %*
)
exit /b %errorlevel%
