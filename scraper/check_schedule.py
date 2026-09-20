"""
Schedule checker for GitHub Actions scraper workflow.
Implements Approach 2:
- Night (23:00 - 06:00 JST): No updates
- Weekdays (except day before weekend/holiday): Every 2 hours (06:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 22:00 JST)
- Day before weekends/holidays: Every 30 minutes during daytime (06:00 - 22:30 JST)
"""

import os
import sys
import argparse
from datetime import datetime, timedelta, timezone

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

def check_schedule(dt_jst, force=False):
    """
    Determine whether to run scraper based on dt_jst.
    Returns (should_run: bool, reason: str)
    """
    if force:
        return True, "Force run requested (--force or workflow_dispatch)"

    hour = dt_jst.hour
    minute = dt_jst.minute

    # 1. Night check (23:00 - 05:59 JST)
    if hour >= 23 or hour < 6:
        return False, f"Nighttime period ({hour:02d}:{minute:02d} JST, active hours: 06:00 - 22:59)"

    # 2. Check if tomorrow is weekend (Sat/Sun) or national holiday
    tomorrow = (dt_jst + timedelta(days=1)).date()
    tomorrow_weekday = tomorrow.weekday() # 0: Mon, ..., 5: Sat, 6: Sun
    tomorrow_is_weekend = tomorrow_weekday in (5, 6)
    tomorrow_is_holiday = is_holiday(tomorrow)

    is_eve_of_weekend_or_holiday = tomorrow_is_weekend or tomorrow_is_holiday
    eve_detail = []
    if tomorrow_is_weekend:
        day_names = ["月", "火", "水", "木", "金", "土", "日"]
        eve_detail.append(f"翌日が{day_names[tomorrow_weekday]}曜")
    if tomorrow_is_holiday:
        h_name = jpholiday.is_holiday_name(tomorrow) if jpholiday else "祝日"
        eve_detail.append(f"翌日が祝日({h_name})")

    # 3. Decision
    if is_eve_of_weekend_or_holiday:
        # Day before weekend/holiday: Run every 30 minutes during daytime
        reason = f"土日祝日の前日 ({', '.join(eve_detail)}): 30分間隔更新対象 ({hour:02d}:{minute:02d} JST)"
        return True, reason
    else:
        # Regular weekday: Run every 2 hours (06:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 22:00 JST)
        # Cron runs every 30 minutes. Run when hour is even and minute is around 00 (minute < 20 to allow for GitHub Actions delay)
        if hour % 2 == 0 and minute < 20:
            reason = f"平日日中 2時間間隔更新 ({hour:02d}:00枠, 現在 {hour:02d}:{minute:02d} JST)"
            return True, reason
        else:
            reason = f"平日日中 2時間間隔スキップ (次回更新は偶数時00分, 現在 {hour:02d}:{minute:02d} JST)"
            return False, reason

def main():
    parser = argparse.ArgumentParser(description="Check if scraper should run according to schedule rules.")
    parser.add_argument("--datetime", type=str, help="Test datetime in 'YYYY-MM-DD HH:MM' (JST)")
    parser.add_argument("--force", action="store_true", help="Force run")
    args = parser.parse_args()

    if args.datetime:
        dt = datetime.strptime(args.datetime, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    else:
        dt = datetime.now(JST)

    should_run, reason = check_schedule(dt, force=args.force)

    print("=" * 60)
    print(f"[Schedule Check] Evaluation Time: {dt.strftime('%Y-%m-%d %H:%M:%S')} JST")
    print(f"[Schedule Check] Should Run:      {'YES (RUN)' if should_run else 'NO (SKIP)'}")
    print(f"[Schedule Check] Reason:          {reason}")
    print("=" * 60)

    # Output to GitHub Actions step output if GITHUB_OUTPUT environment variable exists
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"should_run={'true' if should_run else 'false'}\n")
            f.write(f"reason={reason}\n")
        print(f"[GitHub Actions] Wrote outputs to {github_output}")

if __name__ == "__main__":
    main()
