@echo off
chcp 65001 > nul
title 施設予約システムWebスクレイピング

echo =========================================================
echo  施設予約システムWebスクレイピング開始

python scraper/scrape.py all

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] 予約可能施設データ (docs/data.json, docs/data_city.json) の取得が完了しました。
    echo.
    set /p CHOICE="即時Web表示を開始しますか？ (Y/N): "
    if /i "%CHOICE%"=="Y" (
        call start_server.bat
    )
) else (
    echo.
    echo [ERROR] スクレイピング中にエラーが発生しました。
    pause
)
