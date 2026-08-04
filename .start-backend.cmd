@echo off
setlocal EnableExtensions
call "%~dp0.venv\Scripts\activate.bat"
uvicorn src.main:app --host 0.0.0.0 --port 8000
