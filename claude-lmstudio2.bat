@echo off
set ANTHROPIC_BASE_URL=http://192.168.3.150:1234
set ANTHROPIC_AUTH_TOKEN=lmstudio2
set ANTHROPIC_MODEL=qwen3.6-35b-a3b-claude-4.7-opus-reasoning-distilled-apex
set NO_PROXY=192.168.3.150,localhost,127.0.0.1
echo [LMStudio] %ANTHROPIC_MODEL%
"%USERPROFILE%\AppData\Roaming\npm\claude" %*
