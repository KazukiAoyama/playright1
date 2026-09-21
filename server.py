import os
import sys
import time
import json
import threading
import subprocess
import asyncio
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding='utf-8')

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
DATA_FILES = [
    os.path.join(DOCS_DIR, "data.json"),
    os.path.join(DOCS_DIR, "data_city.json")
]

COOLDOWN_SECONDS = 30 * 60  # 30分 = 1800秒

# State tracking
state_lock = threading.Lock()
is_scraping_running = False
last_scrape_status = {"status": "idle", "message": ""}

# 県スクレイパー（秋ヶ瀬公園）オンタイム取得用キャッシュとロック
pref_lock = threading.Lock()
pref_cache = {
    "timestamp": 0,
    "data": None
}
PREF_CACHE_TTL = 30  # 30秒以内の再アクセスなら直近取得データを即時返却

def get_pref_data_live(force=False):
    """Fetches real-time prefectural park (Akigase) data via Direct API with caching."""
    global pref_cache
    now = time.time()
    
    with pref_lock:
        if not force and pref_cache["data"] and (now - pref_cache["timestamp"] < PREF_CACHE_TTL):
            return pref_cache["data"], False
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] On-time scraping Akigase Park data (Direct API)...")
        try:
            if BASE_DIR not in sys.path:
                sys.path.insert(0, BASE_DIR)
            from scraper.scrape import run_scraper
            result = asyncio.run(run_scraper())
            pref_cache["timestamp"] = time.time()
            pref_cache["data"] = result
            return result, True
        except Exception as e:
            print(f"[ERROR] On-time pref scraping failed: {e}")
            # Fallback to existing data.json if available
            fallback_file = os.path.join(DOCS_DIR, "data.json")
            if os.path.exists(fallback_file):
                try:
                    with open(fallback_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return data, False
                except Exception:
                    pass
            raise e

def get_last_updated_timestamp():
    """Returns the newest modification time of the data json files."""
    mtimes = []
    for f in DATA_FILES:
        if os.path.exists(f):
            mtimes.append(os.path.getmtime(f))
    if mtimes:
        return max(mtimes)
    return 0

def get_cooldown_info():
    """Calculates remaining seconds until refresh is allowed."""
    last_ts = get_last_updated_timestamp()
    if last_ts == 0:
        return 0, True, 0
    elapsed = time.time() - last_ts
    remaining = max(0, int(COOLDOWN_SECONDS - elapsed))
    can_refresh = (remaining == 0) and not is_scraping_running
    return remaining, can_refresh, last_ts

def run_scraper_process():
    """Runs scraper/scrape.py all in a background thread."""
    global is_scraping_running, last_scrape_status
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Background scraper started...")
    start_time = time.time()
    try:
        cmd = [sys.executable, os.path.join(BASE_DIR, "scraper", "scrape.py"), "all"]
        res = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, encoding='utf-8')
        elapsed = int(time.time() - start_time)
        with state_lock:
            is_scraping_running = False
            if res.returncode == 0:
                last_scrape_status = {
                    "status": "success",
                    "message": f"更新が正常に完了しました（所要時間: {elapsed}秒）。",
                    "completed_at": time.time()
                }
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Scraper finished successfully in {elapsed}s.")
            else:
                last_scrape_status = {
                    "status": "error",
                    "message": f"スクレイピング中にエラーが発生しました。\n{res.stderr[:300]}",
                    "completed_at": time.time()
                }
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Scraper failed with code {res.returncode}: {res.stderr[:200]}")
    except Exception as e:
        with state_lock:
            is_scraping_running = False
            last_scrape_status = {
                "status": "error",
                "message": f"プロセス実行時例外: {str(e)}",
                "completed_at": time.time()
            }
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Scraper execution exception: {e}")

class CustomAppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DOCS_DIR, **kwargs)

    def do_GET(self):
        url_path = self.path.split("?")[0]
        if url_path == "/api/status":
            self.send_json_response(self.get_status_payload())
            return
        elif url_path == "/api/pref":
            try:
                force = "force=1" in self.path or "force=true" in self.path
                data, fetched_live = get_pref_data_live(force=force)
                self.send_json_response(data)
            except Exception as e:
                self.send_json_response({"error": str(e)}, status_code=500)
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/refresh":
            global is_scraping_running, last_scrape_status
            remaining, can_refresh, last_ts = get_cooldown_info()

            with state_lock:
                if is_scraping_running:
                    self.send_json_response({
                        "error": "すでにスクレイピングが実行中です。完了までお待ちください。",
                        "is_running": True
                    }, status_code=409)
                    return

                if not can_refresh:
                    rem_min = remaining // 60
                    rem_sec = remaining % 60
                    self.send_json_response({
                        "error": f"前回更新から30分経過するまで更新できません（残り {rem_min}分{rem_sec}秒）。",
                        "remaining_seconds": remaining,
                        "can_refresh": False
                    }, status_code=429)
                    return

                # Start scraping
                is_scraping_running = True
                last_scrape_status = {"status": "running", "message": "スクレイピング実行中..."}
                thread = threading.Thread(target=run_scraper_process, daemon=True)
                thread.start()

            self.send_json_response({
                "status": "started",
                "message": "スクレイピングを開始しました。完了まで約1〜2分かかります。"
            })
            return

        self.send_error(404, "Not Found")

    def get_status_payload(self):
        remaining, can_refresh, last_ts = get_cooldown_info()
        return {
            "is_running": is_scraping_running,
            "can_refresh": can_refresh,
            "remaining_seconds": remaining,
            "cooldown_total_seconds": COOLDOWN_SECONDS,
            "last_updated_ts": last_ts,
            "last_updated_str": datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M:%S") if last_ts > 0 else None,
            "last_scrape_result": last_scrape_status
        }

    def send_json_response(self, data, status_code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress standard access logging to keep terminal clean, or print concise log
        if args and isinstance(args[0], str) and "/api/" in args[0]:
            status = args[1] if len(args) > 1 else ""
            print(f"[{datetime.now().strftime('%H:%M:%S')}] API Request: {args[0]} -> {status}")
        else:
            pass

def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), CustomAppHandler)
    print("=" * 60)
    print("  野球場・ソフトボール場 空き状況ローカルサーバー")
    print(f"  URL: http://localhost:{PORT}")
    print(f"  配信ディレクトリ: {DOCS_DIR}")
    print("  API: GET /api/pref (秋ヶ瀬公園オンタイム取得), GET /api/status, POST /api/refresh")
    print("  停止するには Ctrl+C を押してください")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nサーバーを停止しました。")

if __name__ == "__main__":
    main()
