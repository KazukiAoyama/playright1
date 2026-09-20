import asyncio
import sys
import os
import json
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

sys.stdout.reconfigure(encoding='utf-8')

STATUS_MAP = {
    "0": {"text": "ロック", "symbol": "×", "available": False},
    "1": {"text": "空き", "symbol": "○", "available": True},
    "2": {"text": "電話受付", "symbol": "☎", "available": False},
    "3": {"text": "期間外", "symbol": "-", "available": False},
    "4": {"text": "抽選受付", "symbol": "△", "available": True},
    "5": {"text": "休場", "symbol": "休", "available": False},
    "6": {"text": "点検・不可", "symbol": "×", "available": False},
    "7": {"text": "一般開放", "symbol": "○", "available": True},
    "8": {"text": "予約済", "symbol": "×", "available": False},
    "9": {"text": "仮予約", "symbol": "×", "available": False},
    "10": {"text": "個人利用", "symbol": "×", "available": False},
}

TARGET_URL = "https://saitama-pref-reserve.michi-shiru.jp/facilitysearchcondition"

def fetch_date_slots(target_date, facility_id=8, sub_facility_ids=None):
    """Fetch time slots for a single date directly from the backend reservation API."""
    import urllib.request
    if sub_facility_ids is None:
        sub_facility_ids = [268, 269, 270, 273, 274, 303, 304]

    url = "https://zdjn8hpyod.execute-api.ap-northeast-1.amazonaws.com/prd/us-reservation/reservation-application/facility-list/availability"
    headers = {
        "Content-Type": "application/json",
        "Referer": "https://saitama-pref-reserve.michi-shiru.jp/",
        "Origin": "https://saitama-pref-reserve.michi-shiru.jp",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    payload = {
        "facilityId": facility_id,
        "subFacilityIds": sub_facility_ids,
        "periodRange": "1",
        "usageDate": target_date
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                return data.get("result", {}).get("slots", [])
            else:
                print(f"[WARN] API returned HTTP {res.status} for date {target_date}")
                return []
    except Exception as e:
        print(f"[WARN] Failed to fetch slots for date {target_date}: {e}")
        return []

async def run_scraper():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Saitama Park Reservation Scraper (Direct API Mode)...")
    from concurrent.futures import ThreadPoolExecutor

    facility_id = 8
    # 7 courts: 第2野球場 (1, 2, 3, 6, 7), ソフトボール場 (5, 6)
    sub_facility_ids = [268, 269, 270, 273, 274, 303, 304]

    # Build date list: today + next 60 days
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)
    dates = [(now_jst + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(60)]

    print(f"Fetching availability across 60 days ({dates[0]} to {dates[-1]}) via backend API...")
    loop = asyncio.get_running_loop()

    def fetch_all():
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(fetch_date_slots, d, facility_id, sub_facility_ids) for d in dates]
            all_slots = []
            for f in futures:
                all_slots.extend(f.result())
            return all_slots

    raw_slots = await loop.run_in_executor(None, fetch_all)

    if not raw_slots:
        raise RuntimeError("秋ヶ瀬公園の空き状況データが0件でした（APIエラーまたはアクセス制限の可能性があります）。")

    # Deduplicate and format dataset with morning (午前) and afternoon (午後)
    seen_keys = set()
    formatted_data = []

    for slot in raw_slots:
        key = (slot["subFacilityId"], slot["targetDate"], slot["slotStartTime"], slot["slotEndTime"])
        if key in seen_keys:
            continue
        seen_keys.add(key)

        start_time = slot.get("slotStartTime", "")
        # Categorize into 午前 (Morning) and 午後 (Afternoon)
        if start_time < "12:30:00":
            time_slot_type = "午前"
        else:
            time_slot_type = "午後"

        st_info = STATUS_MAP.get(str(slot.get("slotStatus")), {"text": "不明", "symbol": "?", "available": False})
        formatted_data.append({
            "subFacilityId": slot.get("subFacilityId"),
            "subFacilityName": slot.get("subFacilityName"),
            "timeSlotType": time_slot_type,
            "date": slot.get("targetDate"),
            "startTime": slot.get("slotStartTime"),
            "endTime": slot.get("slotEndTime"),
            "status": slot.get("slotStatus"),
            "statusText": st_info["text"],
            "symbol": st_info["symbol"],
            "available": st_info["available"],
            "lotteryAppNum": slot.get("lotteryAppNum", 0)
        })

    # Sort dataset chronologically, by court name, then by time
    formatted_data.sort(key=lambda x: (x["date"], x["subFacilityName"], x["startTime"]))

    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)
    
    result_json = {
        "updatedAt": now_jst.strftime("%Y-%m-%d %H:%M:%S JST"),
        "facilityName": "秋ヶ瀬公園",
        "purposes": ["軟式野球", "ソフトボール"],
        "totalSlots": len(formatted_data),
        "availableSlotsCount": sum(1 for s in formatted_data if s["available"]),
        "data": formatted_data
    }

    # Output to docs/data.json
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    docs_dir = os.path.join(project_root, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    
    output_path = os.path.join(docs_dir, "data.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)

    morning_count = sum(1 for s in formatted_data if s["timeSlotType"] == "午前")
    afternoon_count = sum(1 for s in formatted_data if s["timeSlotType"] == "午後")

    print(f"\n[SUCCESS] Scraped total {result_json['totalSlots']} time slots!")
    print(f"[SUCCESS] 午前 (Morning) slots: {morning_count}")
    print(f"[SUCCESS] 午後 (Afternoon) slots: {afternoon_count}")
    print(f"[SUCCESS] Total available slots: {result_json['availableSlotsCount']}")
    print(f"[SUCCESS] Saved data file to {output_path}")
    return result_json

async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    errors = []
    successes = []

    if target in ("pref", "all"):
        print("\n==========================================")
        print(">>> 1. 埼玉県営公園（秋ヶ瀬公園）スクレイピング")
        print("==========================================")
        pref_success = False
        for attempt in range(1, 3):
            try:
                print(f"[Prefecture] 試行 {attempt}/2 開始...")
                await run_scraper()
                pref_success = True
                successes.append("pref")
                break
            except Exception as e:
                print(f"[WARN] 埼玉県営公園スクレイピング試行 {attempt} 失敗: {e}")
                if attempt < 2:
                    print("5秒後に再試行します...")
                    await asyncio.sleep(5)
                else:
                    errors.append(("pref", e))

    if target in ("city", "all"):
        print("\n==========================================")
        print(">>> 2. さいたま市公共施設（少年野球場9箇所）スクレイピング")
        print("==========================================")
        city_success = False
        for attempt in range(1, 3):
            try:
                print(f"[City] 試行 {attempt}/2 開始...")
                try:
                    from scraper.saitama_city_scraper import scrape_saitama_city
                except ImportError:
                    from saitama_city_scraper import scrape_saitama_city
                await scrape_saitama_city()
                city_success = True
                successes.append("city")
                break
            except Exception as e:
                print(f"[WARN] さいたま市スクレイピング試行 {attempt} 失敗: {e}")
                if attempt < 2:
                    print("5秒後に再試行します...")
                    await asyncio.sleep(5)
                else:
                    errors.append(("city", e))

    print("\n==========================================")
    print(f"[Result] 成功: {len(successes)} 件, 失敗: {len(errors)} 件")
    print("==========================================")

    # Output summary to GitHub Actions Step Summary if available
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("### スクレイピング実行結果\n\n")
                f.write(f"- 成功: `{', '.join(successes) if successes else 'なし'}`\n")
                if errors:
                    f.write(f"- 失敗: `{', '.join(e[0] for e in errors)}`\n\n")
                    f.write("#### エラー詳細\n")
                    for target_name, err in errors:
                        f.write(f"- **{target_name}**: `{err}`\n")
        except Exception as e:
            print(f"[WARN] Failed to write step summary: {e}")

    # Exit with code 1 if any target failed so GitHub Actions notifies developers
    if errors and not successes:
        print(f"\n[CRITICAL] すべてのスクレイピング対象でエラーが発生しました。")
        sys.exit(1)
    elif errors:
        print(f"\n[PARTIAL ERROR] 一部対象でエラーが発生しました: {[e[0] for e in errors]}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
