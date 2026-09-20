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

async def run_scraper():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Saitama Park Reservation Scraper (Morning & Afternoon)...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()

        print("Navigating to target site:", TARGET_URL)
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)

        # 1. 音声読み上げ予約: 「利用しない」を選択
        print("Selecting '音声読み上げ予約: 利用しない'...")
        await page.locator("input[name='useAcsMode'][value='0']").check()
        await page.wait_for_timeout(300)

        # 2. 利用日: 「日」または「月」選択（セッション確立用）
        await page.locator("input[name='periodRange'][value='1']").check()
        await page.wait_for_timeout(300)

        # 3. 施設: 「秋ヶ瀬公園」を選択
        print("Selecting '施設: 秋ヶ瀬公園'...")
        fac_input = page.locator("input[name='facilityName']")
        await fac_input.fill("秋ヶ瀬公園")
        await page.wait_for_timeout(1000)
        options = await page.locator("li[role='option'], .MuiAutocomplete-option").all()
        for opt in options:
            if "秋ヶ瀬公園" in await opt.inner_text():
                await opt.click()
                break
        await page.wait_for_timeout(300)

        # 4. 利用目的: 「軟式野球」「ソフトボール」を選択
        print("Selecting '利用目的: 軟式野球' & 'ソフトボール'...")
        purp_input = page.locator("input[name='usagePurpose']")
        
        # 軟式野球
        await purp_input.fill("軟式野球")
        await page.wait_for_timeout(1000)
        options = await page.locator("li[role='option'], .MuiAutocomplete-option").all()
        for opt in options:
            if "軟式野球" in await opt.inner_text():
                await opt.click()
                break

        # ソフトボール
        await purp_input.fill("ソフトボール")
        await page.wait_for_timeout(1000)
        options = await page.locator("li[role='option'], .MuiAutocomplete-option").all()
        for opt in options:
            if "ソフトボール" in await opt.inner_text():
                await opt.click()
                break

        # 5. 検索実行
        print("Submitting search condition form...")
        await page.locator("button[type='submit']").click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(3000)

        print("Fetching full availability data (Morning & Afternoon) across date range...")
        # Fetch both morning and afternoon slots for all baseball & softball courts across 60 days
        raw_slots = await page.evaluate("""async () => {
            const facilityId = 8;
            // 7 courts: 第2野球場 (1, 2, 3, 6, 7), ソフトボール場 (5, 6)
            const subFacilityIds = [268, 269, 270, 273, 274, 303, 304];
            
            // Build date list: today + next 60 days
            const dates = [];
            const now = new Date();
            for (let i = 0; i < 60; i++) {
                const d = new Date(now);
                d.setDate(now.getDate() + i);
                const yyyy = d.getFullYear();
                const mm = String(d.getMonth() + 1).padStart(2, '0');
                const dd = String(d.getDate()).padStart(2, '0');
                dates.push(`${yyyy}-${mm}-${dd}`);
            }

            // Fetch in concurrent batches of 6 requests
            const allSlots = [];
            const batchSize = 6;
            for (let i = 0; i < dates.length; i += batchSize) {
                const batchDates = dates.slice(i, i + batchSize);
                const batchPromises = batchDates.map(async (targetDate) => {
                    try {
                        const res = await fetch("https://zdjn8hpyod.execute-api.ap-northeast-1.amazonaws.com/prd/us-reservation/reservation-application/facility-list/availability", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                facilityId,
                                subFacilityIds,
                                periodRange: "1",
                                usageDate: targetDate
                            })
                        });
                        const json = await res.json();
                        return json.result?.slots || [];
                    } catch (e) {
                        return [];
                    }
                });
                const batchResults = await Promise.all(batchPromises);
                batchResults.forEach(slots => allSlots.push(...slots));
            }
            return allSlots;
        }""")

        await browser.close()

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

    # If all attempted targets failed, exit with 1 to notify GitHub Actions
    if errors and not successes:
        print(f"\n[CRITICAL] すべてのスクレイピング対象でエラーが発生しました。")
        sys.exit(1)
    elif errors:
        print(f"\n[PARTIAL] 一部対象でエラーが発生しましたが、取得できた最新データは保持されます。")

if __name__ == "__main__":
    asyncio.run(main())
