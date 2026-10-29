import os
import sys
import json
import urllib.request
import asyncio
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# 日本時間 (JST)
JST = timezone(timedelta(hours=9))

# 日本の祝日マスター (2025 - 2028)
JP_HOLIDAYS = {
    # 2025
    "2025-01-01": "元日", "2025-01-13": "成人の日", "2025-02-11": "建国記念の日", "2025-02-23": "天皇誕生日", "2025-02-24": "振替休日",
    "2025-03-20": "春分の日", "2025-04-29": "昭和の日", "2025-05-03": "憲法記念日", "2025-05-04": "みどりの日", "2025-05-05": "こどもの日", "2025-05-06": "振替休日",
    "2025-07-21": "海の日", "2025-08-11": "山の日", "2025-09-15": "敬老の日", "2025-09-23": "秋分の日", "2025-10-13": "スポーツの日",
    "2025-11-03": "文化の日", "2025-11-23": "勤労感謝の日", "2025-11-24": "振替休日",
    # 2026
    "2026-01-01": "元日", "2026-01-12": "成人の日", "2026-02-11": "建国記念の日", "2026-02-23": "天皇誕生日",
    "2026-03-20": "春分の日", "2026-04-29": "昭和の日", "2026-05-03": "憲法記念日", "2026-05-04": "みどりの日", "2026-05-05": "こどもの日", "2026-05-06": "振替休日",
    "2026-07-20": "海の日", "2026-08-11": "山の日", "2026-09-21": "敬老の日", "2026-09-22": "国民の休日", "2026-09-23": "秋分の日",
    "2026-10-12": "スポーツの日", "2026-11-03": "文化の日", "2026-11-23": "勤労感謝の日",
    # 2027
    "2027-01-01": "元日", "2027-01-11": "成人の日", "2027-02-11": "建国記念の日", "2027-02-23": "天皇誕生日",
    "2027-03-21": "春分の日", "2027-03-22": "振替休日", "2027-04-29": "昭和の日", "2027-05-03": "憲法記念日", "2027-05-04": "みどりの日", "2027-05-05": "こどもの日",
    "2027-07-19": "海の日", "2027-08-11": "山の日", "2027-09-20": "敬老の日", "2027-09-23": "秋分の日", "2027-10-11": "スポーツの日",
    "2027-11-03": "文化の日", "2027-11-23": "勤労感謝の日",
    # 2028
    "2028-01-01": "元日", "2028-01-10": "成人の日", "2028-02-11": "建国記念の日", "2028-02-23": "天皇誕生日",
    "2028-03-20": "春分の日", "2028-04-29": "昭和の日", "2028-05-03": "憲法記念日", "2028-05-04": "みどりの日", "2028-05-05": "こどもの日",
    "2028-07-17": "海の日", "2028-08-11": "山の日", "2028-09-18": "敬老の日", "2028-09-22": "秋分の日", "2028-10-09": "スポーツの日",
    "2028-11-03": "文化の日", "2028-11-23": "勤労感謝の日"
}

DEFAULT_PREF_WORKER_URL = "https://saitama-pref-worker.kazuki-aoyama.workers.dev"

def get_day_type(date_str):
    """'sat', 'sun', 'holiday', 'weekday' のいずれかを返す"""
    if date_str in JP_HOLIDAYS:
        return "holiday"
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = dt.weekday() # 0: Mon, 5: Sat, 6: Sun
    if weekday == 5:
        return "sat"
    elif weekday == 6:
        return "sun"
    return "weekday"

def get_time_slot_type(time_slot_str):
    """'am' または 'pm' を判定"""
    if "午前" in time_slot_str:
        return "am"
    elif "午後" in time_slot_str:
        return "pm"
    return "other"

def make_slot_key(ground_name, court_name, date_str, time_slot_type):
    return f"{ground_name}_{court_name}_{date_str}_{time_slot_type}"

def load_json(filepath, default=None):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to read {filepath}: {e}")
        return default

def save_json(filepath, data):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_pref_data(pref_data_file=None):
    """
    秋ヶ瀬公園の最新空き枠データを取得する。
    1. Cloudflare Worker から取得（GitHub Actions・Web向け、高速）
    2. 失敗時は Direct API（scrape.py）から直接取得
    3. 最終フォールバックとしてローカルの docs/data.json を使用
    取得成功時は docs/data.json を最新に更新する。
    """
    worker_url = os.environ.get("CLOUDFLARE_WORKER_URL") or os.environ.get("PREF_WORKER_URL") or DEFAULT_PREF_WORKER_URL
    worker_url = worker_url.rstrip("/")

    combined_slots = []
    p1_meta = {}

    # 方法1: Cloudflare Worker 経由
    try:
        print(f"[PREF] Fetching Akigase Park data from Cloudflare Worker ({worker_url})...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
        }
        for offset in [0, 30]:
            req_url = f"{worker_url}/api/pref?days=30&offset={offset}&t={int(datetime.now().timestamp() * 1000)}"
            req = urllib.request.Request(req_url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as res:
                if res.status == 200:
                    resp_json = json.loads(res.read().decode("utf-8"))
                    slots = resp_json.get("data", [])
                    combined_slots.extend(slots)
                    if offset == 0:
                        p1_meta = resp_json
                else:
                    print(f"[WARN] Worker returned HTTP {res.status} for offset {offset}")

        if combined_slots:
            seen = set()
            deduped_slots = []
            for s in combined_slots:
                k = (s.get("subFacilityId"), s.get("date"), s.get("startTime"), s.get("timeSlotType"))
                if k not in seen:
                    seen.add(k)
                    deduped_slots.append(s)

            now_jst = datetime.now(JST)
            pref_data = {
                "updatedAt": p1_meta.get("updatedAt") or now_jst.strftime("%Y-%m-%d %H:%M:%S JST"),
                "facilityName": "秋ヶ瀬公園",
                "purposes": ["軟式野球", "ソフトボール"],
                "totalSlots": len(deduped_slots),
                "availableSlotsCount": sum(1 for s in deduped_slots if s.get("available")),
                "data": deduped_slots
            }

            if pref_data_file:
                try:
                    save_json(pref_data_file, pref_data)
                    print(f"[PREF] Successfully fetched {len(deduped_slots)} slots from Worker and saved to {pref_data_file}")
                except Exception as save_err:
                    print(f"[WARN] Failed to cache pref data to {pref_data_file}: {save_err}")
            return pref_data
    except Exception as e:
        print(f"[WARN] Worker fetch failed: {e}")

    # 方法2: Direct API 直接呼び出し (ローカル環境等)
    try:
        print("[PREF] Attempting Direct API scraper fallback...")
        try:
            from scraper.scrape import run_scraper
        except ImportError:
            from scrape import run_scraper

        res = asyncio.run(run_scraper())
        if res and res.get("data"):
            print(f"[PREF] Direct API fallback succeeded: {len(res['data'])} slots.")
            return res
    except Exception as scrape_err:
        print(f"[WARN] Direct API fallback failed: {scrape_err}")

    # 方法3: ローカルファイルから読み込み
    if pref_data_file and os.path.exists(pref_data_file):
        print(f"[PREF] Falling back to local file {pref_data_file}")
        return load_json(pref_data_file, {})
    return {}

def send_line_broadcast(token, text):
    url = "https://api.line.me/v2/bot/message/broadcast"
    payload = {
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as res:
            print(f"[LINE SUCCESS] Status {res.status}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[LINE ERROR] {e.code}: {e.read().decode('utf-8')}")
        return False
    except Exception as e:
        print(f"[LINE EXCEPTION] {e}")
        return False

def check_and_notify(force=False, dry_run=False):
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    settings_file = os.path.join(root_dir, "docs", "notify_settings.json")
    city_data_file = os.path.join(root_dir, "docs", "data_city.json")
    pref_data_file = os.path.join(root_dir, "docs", "data.json")
    state_file = os.path.join(root_dir, "docs", "last_notified_state.json")

    # 1. 設定の読み込み
    settings = load_json(settings_file, {})
    if not settings.get("enabled", True) and not force:
        print("[INFO] LINE通知は設定で無効化されています。")
        return

    allowed_locations = set(settings.get("locations", []))
    target_dates = set(settings.get("targetDates", [])) if "targetDates" in settings else None
    time_slots = settings.get("timeSlots", {"am": True, "pm": True})

    # 2. 空き枠データの読み込み（さいたま市 & 埼玉県営・秋ヶ瀬公園）
    city_data = load_json(city_data_file, {})
    pref_data = fetch_pref_data(pref_data_file)

    all_slots = []
    # さいたま市
    for item in city_data.get("data", []):
        all_slots.append({
            "source": "city",
            "groundName": item.get("groundName", ""),
            "courtName": item.get("courtName") or item.get("subFacilityName", ""),
            "date": item.get("date", ""),
            "timeSlotType": item.get("timeSlotType", ""),
            "available": item.get("available", False),
            "statusText": item.get("statusText", "")
        })

    # 埼玉県営（秋ヶ瀬公園）
    for item in pref_data.get("data", []):
        all_slots.append({
            "source": "pref",
            "groundName": "秋ヶ瀬公園",
            "courtName": item.get("courtName") or item.get("subFacilityName", ""),
            "date": item.get("date", ""),
            "timeSlotType": item.get("timeSlotType", ""),
            "available": item.get("available", False),
            "statusText": item.get("statusText", "")
        })

    # 3. 前回の空き枠状態を読み込み
    state = load_json(state_file, {"availableKeys": []})
    prev_available_keys = set(state.get("availableKeys", []))

    # 現在のすべての空き枠キー（次回比較用）
    current_all_available_keys = set()

    # 4. 条件に合致する「新規の空き枠」を抽出
    now_jst = datetime.now(JST)
    today_str = now_jst.strftime("%Y-%m-%d")

    newly_available_by_location = {} # location -> list of slots

    for s in all_slots:
        ground = s["groundName"]
        court = s["courtName"]
        d_str = s["date"]
        ts_type = s["timeSlotType"]
        is_avail = s["available"]

        # 過去日はスキップ
        if d_str < today_str:
            continue

        key = make_slot_key(ground, court, d_str, ts_type)
        if is_avail:
            current_all_available_keys.add(key)

        # 対象外の場所はスキップ
        if ground not in allowed_locations:
            continue

        # 対象日（具体日）の判定: 平日は完全に除外
        if target_dates is not None:
            if d_str not in target_dates:
                continue
        else:
            day_type = get_day_type(d_str)
            if day_type == "weekday":
                continue

        # 時間帯判定
        ts_category = get_time_slot_type(ts_type)
        if ts_category in time_slots and not time_slots.get(ts_category, False):
            continue

        # 差分判定: 現在空き(○) かつ 前回は空きでなかった場合
        if is_avail and (key not in prev_available_keys or force):
            if ground not in newly_available_by_location:
                newly_available_by_location[ground] = []
            newly_available_by_location[ground].append(s)

    # 初回実行時（prev_available_keys が空）の場合は、大量通知を防ぐため状態保存のみ
    if not prev_available_keys and not force:
        print(f"[INIT] 初回実行のため、現在の空き枠 {len(current_all_available_keys)} 件を記録しました（通知は次回から開始します）。")
        if not dry_run:
            save_json(state_file, {
                "lastChecked": now_jst.isoformat(),
                "availableKeys": list(current_all_available_keys)
            })
        return

    # 5. 新規空き枠があればLINE通知メッセージを作成
    if not newly_available_by_location:
        print("[INFO] 新規の空き枠はありませんでした。")
        if not dry_run:
            save_json(state_file, {
                "lastChecked": now_jst.isoformat(),
                "availableKeys": list(current_all_available_keys)
            })
        return

    total_new_slots = sum(len(slots) for slots in newly_available_by_location.values())
    print(f"[FOUND] {len(newly_available_by_location)} 箇所、合計 {total_new_slots} 件の新規空き枠を検知！")

    # メッセージ構築（場所単位で集約）
    lines = [
        "⚾ 【空き枠通知】グラウンドに空きが出ました！",
        ""
    ]

    day_kanji = ["月", "火", "水", "木", "金", "土", "日"]

    for ground, slots in newly_available_by_location.items():
        lines.append(f"📍 {ground} ({len(slots)}枠)")
        
        # 日付・時間帯ごとにグルーピング
        grouped = {}
        for s in slots:
            dt = datetime.strptime(s["date"], "%Y-%m-%d")
            w_str = day_kanji[dt.weekday()]
            hol = JP_HOLIDAYS.get(s["date"])
            day_label = f"{w_str}・祝" if hol else w_str
            d_label = f"{s['date'][5:].replace('-', '/')}({day_label}) {s['timeSlotType']}"
            if d_label not in grouped:
                grouped[d_label] = []
            grouped[d_label].append(s["courtName"])

        for d_label, courts in grouped.items():
            courts_str = "、".join(courts[:4])
            if len(courts) > 4:
                courts_str += f" 他{len(courts)-4}面"
            lines.append(f"  ・{d_label}: {courts_str}")
        lines.append("")

    lines.append("🔗 予約サイト:")
    if any(s.get("source") == "city" for slots in newly_available_by_location.values()):
        lines.append("・さいたま市: https://saitama.rsv.ws-scs.jp/web/")
    if any(s.get("source") == "pref" for slots in newly_available_by_location.values()):
        lines.append("・埼玉県営: https://saitama-pref-reserve.michi-shiru.jp/facilitysearchcondition")

    message_text = "\n".join(lines).strip()
    print("--- 通知メッセージ内容 ---")
    print(message_text)
    print("-------------------------")

    if dry_run:
        print("[DRY-RUN] LINE送信および状態ファイル保存をスキップしました。")
        return

    # 6. LINE送信
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    # ローカル実行時のフォールバックトークン
    if not token:
        token = "FSkVnkfWa5vd7fgUDd6mIdDvXPheZRde7hGpinCoE9JEr4uikfDO/Ca1xlSx7z0msKq3/vgPRKe7tDrhXO6ogKv3ClQLadospyrSAyJVM6sWKoA4tomLhH07R16nCklczjgDZeL9Z6+vEm77ppI3WwdB04t89/1O/w1cDnyilFU="

    if token:
        success = send_line_broadcast(token, message_text)
        if success:
            print("[SUCCESS] LINEへの空き枠通知が完了しました。")
    else:
        print("[WARN] LINE_CHANNEL_ACCESS_TOKEN が未設定のため、LINE送信をスキップしました。")

    # 7. 最新状態を保存
    save_json(state_file, {
        "lastChecked": now_jst.isoformat(),
        "availableKeys": list(current_all_available_keys),
        "lastNotifiedAt": now_jst.isoformat(),
        "lastNotifiedSlotsCount": total_new_slots
    })

if __name__ == "__main__":
    force_run = "--force" in sys.argv
    dry_run = "--dry-run" in sys.argv
    check_and_notify(force=force_run, dry_run=dry_run)
