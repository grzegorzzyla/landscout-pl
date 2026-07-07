@echo off
rem cdp - wrapper cmd/PATH dla bin\cdp.ps1 (Claude Code CLI). Patrz bin\README.md.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cdp.ps1" %*
