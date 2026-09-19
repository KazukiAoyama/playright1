import asyncio
import os
import sys
import re
import json
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

TOP_URL = "https://saitama.rsv.ws-scs.jp/web/index.jsp"

# Target 9 grounds specified by the user
TARGET_GROUNDS = [
    {"name": "荒川総合運動公園", "code": "4020"},
    {"name": "八王子公園", "code": "4110"},
    {"name": "見沼臨時グラウンド", "code": "4320"},
    {"name": "大間木公園", "code": "4310"},
    {"name": "浦和総合運動場", "code": "4000"},
    {"name": "さくら草公園", "code": "4120"},
    {"name": "宝来運動公園", "code": "4090"},
    {"name": "西遊馬公園", "code": "4050"},
    {"name": "三橋総合公園", "code": "4060"},
]

# Official Japanese Holidays 2026
HOLIDAYS_2026 = {
    (2026, 1, 1): "元日",
    (2026, 1, 12): "成人の日",
    (2026, 2, 11): "建国記念の日",
    (2026, 2, 23): "天皇誕生日",
    (2026, 3, 20): "春分の日",
    (2026, 4, 29): "昭和の日",
    (2026, 5, 3): "憲法記念日",
    (2026, 5, 4): "みどりの日",
    (2026, 5, 5): "こどもの日",
    (2026, 5, 6): "振替休日",
    (2026, 7, 20): "海の日",
    (2026, 8, 11): "山の日",
    (2026, 9, 21): "敬老の日",
    (2026, 9, 22): "国民の休日",
    (2026, 9, 23): "秋分の日",
    (2026, 10, 12): "スポーツの日",
    (2026, 11, 3): "文化の日",
    (2026, 11, 23): "勤労感謝の日",
}

def is_target_day(dt: datetime):
    is_weekend = dt.weekday() in (5, 6)
    holiday = HOLIDAYS_2026.get((dt.year, dt.month, dt.day), "")
    return (is_weekend or bool(holiday)), holiday

def parse_week_view(html: str):
    """Parses week view to extract exact time slot availability."""
    soup = BeautifulSoup(html, "html.parser")
    resolved = {}  # (year, month, day, period) -> (status, symbol, text, available)

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        date_header_cells = None
        for r in rows:
            cells = r.find_all(["th", "td"])
            txts = [c.get_text(strip=True) for c in cells]
            if len(txts) >= 8 and "2026年" in txts[0] and "月" in txts[1]:
                date_header_cells = cells
                break
        if not date_header_cells:
            continue

        year_str = date_header_cells[0].get_text(strip=True)
        year_m = re.search(r'(\d{4})', year_str)
        year = int(year_m.group(1)) if year_m else 2026

        days_info = []
        for c in date_header_cells[1:]:
            txt = c.get_text(strip=True)
            dm = re.search(r'(\d{1,2})月(\d{1,2})日', txt)
            if dm:
                days_info.append((year, int(dm.group(1)), int(dm.group(2))))

        for r in rows:
            cells = r.find_all(["th", "td"])
            if not cells:
                continue
            period = cells[0].get_text(strip=True)
            if period in ["午前", "午後", "夜間１", "夜間２", "夜間"]:
                for idx, c in enumerate(cells[1:]):
                    if idx < len(days_info):
                        y, m, d = days_info[idx]
                        imgs = c.find_all("img")
                        src = imgs[0].get("src", "") if imgs else ""
                        alt = imgs[0].get("alt", "") if imgs else ""

                        if "empty" in src or alt in ["空き", "空"]:
                            st, sym, desc, avail = "available", "○", "空き", True
                        elif "finish" in src or any(t in src for t in ["1300", "1700", "2100"]) or alt in ["予約あり", "済"]:
                            st, sym, desc, avail = "full", "×", "予約あり", False
                        elif "aki1" in src or alt in ["保守日", "保", "休館日", "休"]:
                            st, sym, desc, avail = "closed", "-", "休館/保守", False
                        else:
                            st, sym, desc, avail = "unavailable", "-", "期間外", False

                        resolved[(y, m, d, period)] = (st, sym, desc, avail)
        if resolved:
            break
    return resolved

async def resolve_partial_days(page, html: str):
    """Finds days marked with '一部空き' and opens week view to get exact morning/afternoon statuses."""
    soup = BeautifulSoup(html, "html.parser")
    partial_days = []

    for a in soup.find_all("a"):
        href = a.get("href", "")
        img = a.find("img")
        alt = img.get("alt", "") if img else ""
        if "一部空き" in alt and "selectDay" in href:
            # extract year, month, day: selectDay(..., mode, year, month, day)
            m = re.search(r'selectDay.*,\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*\)', href)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                partial_days.append((y, mo, d))

    if not partial_days:
        return {}

    resolved_slots = {}
    already_covered = set()

    for (y, mo, d) in partial_days:
        if (y, mo, d) in already_covered:
            continue

        # Target link with selectDay for this date
        selector = f"a[href*='{y}, {mo}, {d}'], a[href*='{y},{mo},{d}']"
        link_elem = page.locator(selector)
        if await link_elem.count() > 0:
            try:
                async with page.expect_navigation(timeout=15000):
                    await link_elem.first.click()

                week_html = await page.content()
                week_data = parse_week_view(week_html)
                for (wy, wm, wd, wp), val in week_data.items():
                    resolved_slots[(wy, wm, wd, wp)] = val
                    already_covered.add((wy, wm, wd))

                # Navigate back to month view
                back_btn = page.locator("a:has(img[alt='もどる'])")
                if await back_btn.count() > 0:
                    async with page.expect_navigation(timeout=15000):
                        await back_btn.first.click()
            except Exception as e:
                print(f"      [WARN] 一部空き詳細取得スキップ ({y}-{mo}-{d}): {e}", flush=True)

    return resolved_slots

def parse_calendar_html(html: str, ground_name: str, resolved_slots: dict = None):
    soup = BeautifulSoup(html, "html.parser")
    resolved_slots = resolved_slots or {}

    # Determine court name
    h_link = soup.find("a", href=re.compile(r'city\.saitama\.jp'))
    court_name = "グラウンド"
    if h_link and h_link.parent:
        full_title = h_link.parent.get_text(" ", strip=True)
        c_name = full_title.replace(ground_name, "").replace("空き状況", "").replace("\xa0", "").strip()
        if c_name:
            court_name = c_name

    # Determine year and month
    header_m = soup.find(string=re.compile(r'(\d{4})年(\d{1,2})月'))
    if not header_m:
        return ground_name, court_name, []
    m_match = re.search(r'(\d{4})年(\d{1,2})月', header_m)
    year = int(m_match.group(1))
    month = int(m_match.group(2))

    slots = []
    seen_days = set()

    for tr in soup.find_all("tr"):
        for td in tr.find_all(["td"]):
            text = td.get_text(strip=True)
            day_match = re.search(r'^(\d{1,2})日', text)
            if not day_match:
                continue
            day = int(day_match.group(1))
            if day in seen_days:
                continue
            seen_days.add(day)

            dt = datetime(year, month, day)
            is_wk_hol, holiday_name = is_target_day(dt)

            imgs = [img.get("alt", "") for img in td.find_all("img") if img.get("alt")]
            status_img = imgs[0] if imgs else ""

            # Check if this day was resolved via week view
            k_m = (year, month, day, "午前")
            k_a = (year, month, day, "午後")

            if k_m in resolved_slots and k_a in resolved_slots:
                m_stat, m_sym, m_desc, m_avail = resolved_slots[k_m]
                a_stat, a_sym, a_desc, a_avail = resolved_slots[k_a]
            elif "全て空き" in status_img:
                m_stat, a_stat = "available", "available"
                m_sym, a_sym = "○", "○"
                m_desc, a_desc = "空き", "空き"
                m_avail, a_avail = True, True
            elif "一部空き" in status_img:
                # If resolution wasn't available, check individual slots
                if k_m in resolved_slots:
                    m_stat, m_sym, m_desc, m_avail = resolved_slots[k_m]
                else:
                    m_stat, m_sym, m_desc, m_avail = "partial", "△", "一部空き", True
                if k_a in resolved_slots:
                    a_stat, a_sym, a_desc, a_avail = resolved_slots[k_a]
                else:
                    a_stat, a_sym, a_desc, a_avail = "partial", "△", "一部空き", True
            elif "予約あり" in status_img:
                m_stat, a_stat = "full", "full"
                m_sym, a_sym = "×", "×"
                m_desc, a_desc = "予約あり", "予約あり"
                m_avail, a_avail = False, False
            elif "休館日" in status_img or "保守日" in status_img:
                m_stat, a_stat = "closed", "closed"
                m_sym, a_sym = "-", "-"
                m_desc, a_desc = "休館/保守", "休館/保守"
                m_avail, a_avail = False, False
            else:
                m_stat, a_stat = "unavailable", "unavailable"
                m_sym, a_sym = "-", "-"
                m_desc, a_desc = "期間外", "期間外"
                m_avail, a_avail = False, False

            date_str = dt.strftime("%Y-%m-%d")
            day_of_week = ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]
            full_sub_name = f"{ground_name} {court_name}".strip()

            slots.append({
                "groundName": ground_name,
                "subFacilityName": full_sub_name,
                "courtName": court_name,
                "timeSlotType": "午前",
                "date": date_str,
                "dayOfWeek": day_of_week,
                "isWeekendOrHoliday": is_wk_hol,
                "holidayName": holiday_name,
                "startTime": "09:00:00",
                "endTime": "13:00:00",
                "status": m_stat,
                "statusText": m_desc,
                "symbol": m_sym,
                "available": m_avail
            })
            slots.append({
                "groundName": ground_name,
                "subFacilityName": full_sub_name,
                "courtName": court_name,
                "timeSlotType": "午後",
                "date": date_str,
                "dayOfWeek": day_of_week,
                "isWeekendOrHoliday": is_wk_hol,
                "holidayName": holiday_name,
                "startTime": "13:00:00",
                "endTime": "17:00:00",
                "status": a_stat,
                "statusText": a_desc,
                "symbol": a_sym,
                "available": a_avail
            })

    return ground_name, court_name, slots

async def scrape_saitama_city():
    print("=== さいたま市公共施設予約システム スクレイピング開始 ===", flush=True)
    all_slots = []
    ground_summary = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("1. トップページへアクセス...", flush=True)
        await page.goto(TOP_URL, wait_until="domcontentloaded", timeout=30000)

        print("2. 施設の空き状況へ遷移...", flush=True)
        async with page.expect_navigation():
            await page.locator("img[alt='施設の空き状況']").click()

        print("3. 利用目的から > 屋外スポーツ > 軟式野球（少年）へ遷移...", flush=True)
        async with page.expect_navigation():
            await page.locator("img[alt='利用目的から']").click()
        async with page.expect_navigation():
            await page.locator("text=屋外スポーツ").click()
        async with page.expect_navigation():
            await page.locator("text=軟式野球（少年）").click()

        print("4. 館選択画面（指定URL）に到達しました", flush=True)

        for g_idx, ground in enumerate(TARGET_GROUNDS):
            g_name = ground["name"]
            print(f"\n[{g_idx+1}/{len(TARGET_GROUNDS)}] グラウンド巡回中: {g_name}...", flush=True)

            target_link = page.locator(f"a:has-text('{g_name}')")
            if await target_link.count() == 0:
                print(f"  警告: {g_name} のリンクが見つかりません。スキップします。", flush=True)
                continue

            async with page.expect_navigation():
                await target_link.first.click()

            # Check if this is facility selection page (multi-facility) or direct month view (single-facility)
            page_title = await page.title()
            is_facility_select = "施設選択画面" in page_title or await page.locator("text=すべて").count() > 0

            courts_scraped = 0
            if is_facility_select:
                print(f"  {g_name}: 複数施設あり。すべてを選択して巡回開始...", flush=True)
                async with page.expect_navigation():
                    await page.locator("text=すべて").first.click()

                # Loop through all facilities via 次の施設
                while True:
                    courts_scraped += 1
                    # Month 1 (当月)
                    html_m1 = await page.content()
                    resolved_m1 = await resolve_partial_days(page, html_m1)
                    if resolved_m1:
                        # Re-read content after returning to month view
                        html_m1 = await page.content()

                    _, court_name, s1 = parse_calendar_html(html_m1, g_name, resolved_m1)
                    all_slots.extend(s1)
                    print(f"    面: {court_name} (当月 {len(s1)} 枠取得, 一部空き詳細解決: {len(resolved_m1)//2}日)", flush=True)

                    # Next Month (翌月)
                    next_month_btn = page.locator("a:has(img[alt='次の月'])")
                    if await next_month_btn.count() > 0:
                        async with page.expect_navigation():
                            await next_month_btn.first.click()
                        html_m2 = await page.content()
                        resolved_m2 = await resolve_partial_days(page, html_m2)
                        if resolved_m2:
                            html_m2 = await page.content()

                        _, _, s2 = parse_calendar_html(html_m2, g_name, resolved_m2)
                        all_slots.extend(s2)

                        # Return to Month 1 before navigating to next facility
                        prev_month_btn = page.locator("a:has(img[alt='前の月'])")
                        if await prev_month_btn.count() > 0:
                            async with page.expect_navigation():
                                await prev_month_btn.first.click()

                    # Check next facility button
                    next_fac_btn = page.locator("a:has(img[alt='次の施設'])")
                    if await next_fac_btn.count() > 0:
                        async with page.expect_navigation():
                            await next_fac_btn.first.click()
                    else:
                        break

                # Go back to 館選択画面
                back_btn = page.locator("a:has(img[alt='もどる'])")
                if await back_btn.count() > 0:
                    async with page.expect_navigation():
                        await back_btn.first.click()

                # If still on 施設選択画面, click back once more
                if "施設選択画面" in (await page.title()) or "InstAction" in page.url:
                    back_btn2 = page.locator("a:has(img[alt='もどる'])")
                    if await back_btn2.count() > 0:
                        async with page.expect_navigation():
                            await back_btn2.first.click()

            else:
                # Single facility
                courts_scraped = 1
                # Month 1
                html_m1 = await page.content()
                resolved_m1 = await resolve_partial_days(page, html_m1)
                if resolved_m1:
                    html_m1 = await page.content()

                _, court_name, s1 = parse_calendar_html(html_m1, g_name, resolved_m1)
                all_slots.extend(s1)
                print(f"    面: {court_name} (当月 {len(s1)} 枠取得, 一部空き詳細解決: {len(resolved_m1)//2}日)", flush=True)

                # Month 2
                next_month_btn = page.locator("a:has(img[alt='次の月'])")
                if await next_month_btn.count() > 0:
                    async with page.expect_navigation():
                        await next_month_btn.first.click()
                    html_m2 = await page.content()
                    resolved_m2 = await resolve_partial_days(page, html_m2)
                    if resolved_m2:
                        html_m2 = await page.content()

                    _, _, s2 = parse_calendar_html(html_m2, g_name, resolved_m2)
                    all_slots.extend(s2)

                # Go back to 館選択画面
                back_btn = page.locator("a:has(img[alt='もどる'])")
                if await back_btn.count() > 0:
                    async with page.expect_navigation():
                        await back_btn.first.click()

            ground_summary.append({
                "groundName": g_name,
                "courtCount": courts_scraped
            })

        await browser.close()

    # Deduplicate slots by (groundName, subFacilityName, date, timeSlotType)
    unique_slots_map = {}
    for slot in all_slots:
        key = (slot["groundName"], slot["subFacilityName"], slot["date"], slot["timeSlotType"])
        unique_slots_map[key] = slot

    final_slots = list(unique_slots_map.values())
    final_slots.sort(key=lambda s: (s["date"], s["groundName"], s["subFacilityName"], s["timeSlotType"]))

    available_count = sum(1 for s in final_slots if s["available"])
    weekend_hol_slots = [s for s in final_slots if s["isWeekendOrHoliday"]]
    weekend_hol_avail = sum(1 for s in weekend_hol_slots if s["available"])

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S JST")
    output_data = {
        "updatedAt": now_str,
        "facilityCategory": "さいたま市公共施設予約システム（少年野球場）",
        "targetUrl": "https://saitama.rsv.ws-scs.jp/web/rsvWTransInstSrchBuildAction.do",
        "targetGrounds": [g["name"] for g in TARGET_GROUNDS],
        "groundsSummary": ground_summary,
        "totalSlots": len(final_slots),
        "availableSlotsCount": available_count,
        "weekendHolidaySlots": len(weekend_hol_slots),
        "weekendHolidayAvailable": weekend_hol_avail,
        "data": final_slots
    }

    out_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "data_city.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n=== スクレイピング完了 ===", flush=True)
    print(f"出力ファイル: {out_path}", flush=True)
    print(f"取得グラウンド数: {len(ground_summary)} / {len(TARGET_GROUNDS)}", flush=True)
    print(f"総スロット数: {len(final_slots)} (うち土日祝: {len(weekend_hol_slots)})", flush=True)
    print(f"土日祝 空きスロット: {weekend_hol_avail} 枠", flush=True)
    return output_data

if __name__ == "__main__":
    asyncio.run(scrape_saitama_city())
