@echo off
chcp 65001 >nul
title 生态Agent - 启动 SearXNG 自托管搜索
cd /d "%~dp0"

echo ============================================
echo  生态Agent - SearXNG 自托管搜索启动器
echo ============================================

REM 检查 Docker
docker version >nul 2>&1
if errorlevel 1 (
    echo [X] 未检测到 Docker, 请先安装并启动 Docker Desktop
    echo     下载: https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

REM 初始化目录
if not exist config mkdir config
if not exist data mkdir data

REM 首次运行: 从模板生成 settings.yml 并写入随机 secret_key
if not exist config\settings.yml (
    if not exist settings.yml.example (
        echo [X] 缺少 settings.yml.example 模板, 请检查文件完整性
        pause
        exit /b 1
    )
    echo [..] 正在生成 config\settings.yml 并写入随机 secret_key ...
    powershell -NoProfile -Command "$k=-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) }); (Get-Content -Raw 'settings.yml.example') -replace 'REPLACE_WITH_SECRET_KEY', $k | Set-Content -Encoding UTF8 'config\settings.yml'"
    echo [OK] 配置已生成
) else (
    echo [..] 使用已有配置 config\settings.yml
)

echo [..] 正在拉取并启动 SearXNG 容器 ...
docker compose -f searxng-docker-compose.yml up -d

REM 等待就绪
set /a tries=0
:wait
set /a tries+=1
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -Uri 'http://localhost:8888/healthz' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo [OK] SearXNG 已就绪: http://localhost:8888
) else (
    if %tries% lss 30 (
        timeout /t 2 /nobreak >nul
        goto wait
    ) else (
        echo [X] 等待超时, 请检查 Docker 日志: docker logs searxng
    )
)

echo.
echo 启动完成后, 在 Agent 设置中确认:
echo   base_url: http://localhost:8888
echo   enabled : true
echo 即自动启用 SearXNG 作为首选搜索, 失败自动降级爬虫引擎.
echo.
pause
