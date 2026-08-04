@echo off
setlocal EnableExtensions
call "%~dp0.venv\Scripts\activate.bat"
celery -A src.celery_app worker --loglevel=info --pool=solo
