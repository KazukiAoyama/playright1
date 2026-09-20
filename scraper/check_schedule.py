"""
Schedule checker for GitHub Actions scraper workflow.
Determines whether to execute scraping based on:
1. Active hours: 06:00 - 22:59 JST (Nighttime 23:00 - 05:59 is skipped)
2. Frequency:
   - Weekends, national holidays, and the day before weekends/holidays:
     High-frequency (target: 30 minutes). Executes if elapsed time since last update >= 20 minutes.
   - Regular weekdays:
     Standard-frequency (target: 2 hours). Executes if elapsed time since last update >= 90 minutes.
3. Fallback:
   - If previous update timestamp cannot be determined, executes by default.
"""

import os
import sys
import argparse
import json
import re
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

try:
    import jpholiday
except ImportError:
    jpholiday = None

JST = timezone(timedelta(hours=9))

def is_holiday(dt_date):
    """Check if the given date is a Japanese national holiday."""
    if jpholiday is not None:
        return jpholiday.is_holiday(dt_date)
    return False

def get_holiday_name(dt_date):
    """Get national holiday name."""
    if jpholiday is not None:
        return jpholiday.is_holiday_name(dt_date)
    return ""

def parse_updated_at(raw_str):
    """Parse updatedAt string (e.g. '2026-09-20 19:02:10 JST') to timezone-aware datetime."""
    if not raw_str or not isinstance(raw_str, str):
        return None
    cleaned = raw_str.replace(" JST", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=JST)
        except ValueError:
            continue
    return None

def get_latest_data_timestamp(project_root):
    """
    Check docs/data.json and docs/data_city.json to find the latest updatedAt.
    Returns (datetime or None, source_filename or None)
    """
    candidates = [
        os.path.join(project_root, "docs", "data.json"),
        os.path.join(project_root, "docs", "data_city.json")
    ]
    latest_dt = None
    latest_src = None

    for file_path in candidates:
        if not os.path.exists(file_path):
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            updated_at_str = data.get("updatedAt")
            parsed_dt = parse_updated_at(updated_at_str)
            if parsed_dt:
                if latest_dt is None or parsed_dt > latest_dt:
                    latest_dt = parsed_dt
                    latest_src = os.path.basename(file_path)
        except Exception as e:
            print(f"[WARN] Failed to read timestamp from {file_path}: {e}")

    return latest_dt, latest_src

def check_schedule(dt_jst, project_root=None, force=False):
    """
    Determine whether to run scraper based on dt_jst and elapsed time since last run.
    Returns (should_run: bool, reason: str)
    """
    if force:
        return True, "Force run requested (--force or workflow_dispatch)"

    hour = dt_jst.hour
    minute = dt_jst.minute

    # 1. Night check (23:00 - 05:59 JST)
    if hour >= 23 or hour < 6:
        return False, f"Nighttime period ({hour:02d}:{minute:02d} JST, active hours: 06:00 - 22:59)"

    # 2. Check today & tomorrow for weekend / holiday status
    today = dt_jst.date()
    tomorrow = today + timedelta(days=1)
    day_names = ["月", "火", "水", "木", "金", "土", "日"]

    today_weekday = today.weekday()
    tomorrow_weekday = tomorrow.weekday()

    today_is_weekend = today_weekday in (5, 6)
    today_is_holiday = is_holiday(today)

    tomorrow_is_weekend = tomorrow_weekday in (5, 6)
    tomorrow_is_holiday = is_holiday(tomorrow)

    status_reasons = []
    if today_is_weekend:
        status_reasons.append(f"本日が{day_names[today_weekday]}曜")
    if today_is_holiday:
        h_name = get_holiday_name(today) or "祝日"
        status_reasons.append(f"本日が祝日({h_name})")
    if tomorrow_is_weekend:
        status_reasons.append(f"翌日が{day_names[tomorrow_weekday]}曜")
    if tomorrow_is_holiday:
        h_name = get_holiday_name(tomorrow) or "祝日"
        status_reasons.append(f"翌日が祝日({h_name})")

    is_high_frequency = bool(status_reasons)

    # 3. Retrieve latest update timestamp
    if project_root is None:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    latest_dt, latest_src = get_latest_data_timestamp(project_root)

    # If no valid timestamp is found, run to generate fresh data
    if latest_dt is None:
        return True, f"前回の更新記録が見つからないため、初回または強制実行します (現在 {hour:02d}:{minute:02d} JST)"

    elapsed = (dt_jst - latest_dt).total_seconds() / 60.0
    elapsed_str = f"前回更新から {elapsed:.1f}分経過 (最終: {latest_dt.strftime('%H:%M:%S')} [{latest_src}])"

    # 4. Frequency Decision based on elapsed time
    if is_high_frequency:
        category_label = f"土日祝・祝前日 ({', '.join(status_reasons)}) [目標: 30分間隔]"
        # Threshold: 20 minutes (allows slight early triggers while preventing redundant back-to-back runs)
        if elapsed >= 20.0:
            return True, f"{category_label}: 更新対象 - {elapsed_str} (閾値 20分以上)"
        else:
            return False, f"{category_label}: スキップ - {elapsed_str} (閾値 20分未満のため待機)"
    else:
        category_label = f"平日日中 [目標: 2時間間隔]"
        # Threshold: 90 minutes (1.5 hours) ensures delay-tolerant 2-hour cycles
        if elapsed >= 90.0:
            return True, f"{category_label}: 更新対象 - {elapsed_str} (閾値 90分以上)"
        else:
            return False, f"{category_label}: スキップ - {elapsed_str} (閾値 90分未満のため待機)"

def main():
    parser = argparse.ArgumentParser(description="Check if scraper should run according to schedule rules.")
    parser.add_argument("--datetime", type=str, help="Test datetime in 'YYYY-MM-DD HH:MM' (JST)")
    parser.add_argument("--force", action="store_true", help="Force run")
    args = parser.parse_args()

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    if args.datetime:
        dt = datetime.strptime(args.datetime, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    else:
        dt = datetime.now(JST)

    should_run, reason = check_schedule(dt, project_root=project_root, force=args.force)

    print("=" * 60)
    print(f"[Schedule Check] Evaluation Time: {dt.strftime('%Y-%m-%d %H:%M:%S')} JST")
    print(f"[Schedule Check] Should Run:      {'YES (RUN)' if should_run else 'NO (SKIP)'}")
    print(f"[Schedule Check] Reason:          {reason}")
    print("=" * 60)

    # Output to GitHub Actions step output if GITHUB_OUTPUT exists
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"should_run={'true' if should_run else 'false'}\n")
            f.write(f"reason={reason}\n")
        print(f"[GitHub Actions] Wrote outputs to {github_output}")

    # Output to GitHub Step Summary if GITHUB_STEP_SUMMARY exists
    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as f:
            f.write(f"### 🕒 スケジュール判定結果\n")
            f.write(f"- **判定**: `{'実行 (RUN)' if should_run else 'スキップ (SKIP)'}`\n")
            f.write(f"- **評価時刻**: `{dt.strftime('%Y-%m-%d %H:%M:%S')} JST`\n")
            f.write(f"- **判定理由**: {reason}\n")

if __name__ == "__main__":
    main()

