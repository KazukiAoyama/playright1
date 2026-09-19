@echo off
title 施設空き状況データ収集 (スクレイパー実行)

echo =========================================================
echo  野球場・ソフトボール場 空き状況収集スクリプト
echo  - 埼玉県営公園（秋ヶ瀬公園）
echo  - さいたま市（少年野球場 9グラウンド）
echo =========================================================
echo.
echo スクレイピングを実行し、最新のデータを取得しています...
echo.

python scraper/scrape.py all

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [成功] 最新の空き状況データ (docs/data.json, docs/data_city.json) の更新が完了しました。
    echo.
    set /p CHOICE="ローカルWebサーバーを起動してブラウザで確認しますか？ (Y/N): "
    if /i "%CHOICE%"=="Y" (
        call start_server.bat
    )
) else (
    echo.
    echo [エラー] スクレイピングの実行中にエラーが発生しました。
    pause
)
