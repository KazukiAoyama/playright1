@echo off
chcp 65001 > nul
title 施設予約システムWebスクレイピング

echo =========================================================
echo  施設予約システムWebスクレイピング開始
echo =========================================================

python scraper/scrape.py all

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] 予約可能施設データ (docs/data.json, docs/data_city.json) の取得が完了しました。
    echo.
    echo ---------------------------------------------------------
    echo  GitHub (GitHub Pages 公開サイト) への最新データ反映
    echo ---------------------------------------------------------
    set /p SYNC_CHOICE="GitHubサイトのデータ・更新日時を今すぐ更新しますか？ (Y/N) [初期値: Y]: "
    if "%SYNC_CHOICE%"=="" set SYNC_CHOICE=Y
    if /i "%SYNC_CHOICE%"=="Y" (
        echo.
        echo [Git] 最新データをコミット＆プッシュしています...
        git add docs/data.json docs/data_city.json
        git commit -m "auto: update availability data (manual run)"
        git push origin main
        if %ERRORLEVEL% EQU 0 (
            echo [OK] GitHubへの反映が完了しました！公開サイトの更新日時も更新されます。
        ) else (
            echo [WARN] GitHubへのプッシュ中にエラーが発生しました。ネットワーク設定や権限をご確認ください。
        )
    )

    echo.
    set /p CHOICE="ローカルWeb表示(サーバー)を開始しますか？ (Y/N) [初期値: N]: "
    if /i "%CHOICE%"=="Y" (
        call start_server.bat
    )
) else (
    echo.
    echo [ERROR] スクレイピング中にエラーが発生しました。
    pause
)

