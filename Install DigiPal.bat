@echo off
title Install DigiPal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_digipal.ps1"
if errorlevel 1 pause
