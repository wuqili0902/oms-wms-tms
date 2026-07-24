@echo off
set ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
set ANTHROPIC_MODEL=deepseek-v4-flash
set ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-flash
set ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-flash
set ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
set CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash
set CLAUDE_CODE_EFFORT_LEVEL=max

if "%ANTHROPIC_AUTH_TOKEN%"=="" (
    if exist "%USERPROFILE%\.claude\deepseek-key.txt" (
        set /p ANTHROPIC_AUTH_TOKEN=<"%USERPROFILE%\.claude\deepseek-key.txt"
    ) else (
        set /p ANTHROPIC_AUTH_TOKEN=Please enter DeepSeek API Key:
    )
)

claude
