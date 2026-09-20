@echo off
chcp 65001 > nul
title 野球場・ソフトボール場 空き状況ローカルサーバー

echo =========================================================
echo  野球場・ソフトボール場 空き状況ローカルWebサーバー起動
echo =========================================================
echo.
echo [1/2] ブラウザで http://localhost:8000 を開きます...
start http://localhost:8000

echo [2/2] ローカルWebサーバーを起動します (停止するには Ctrl+C)...
echo.
python server.py

pause
