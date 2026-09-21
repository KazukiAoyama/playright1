/**
 * Cloudflare Worker: 埼玉県県営公園（秋ヶ瀬公園）施設予約 Direct API プロキシ & オンタイム取得
 */

const TARGET_API_URL = "https://zdjn8hpyod.execute-api.ap-northeast-1.amazonaws.com/prd/us-reservation/reservation-application/facility-list/availability";

const STATUS_MAP = {
  "0": { text: "ロック", symbol: "×", available: false },
  "1": { text: "空き", symbol: "○", available: true },
  "2": { text: "電話受付", symbol: "☎", available: false },
  "3": { text: "期間外", symbol: "-", available: false },
  "4": { text: "抽選受付", symbol: "△", available: true },
  "5": { text: "休場", symbol: "休", available: false },
  "6": { text: "点検・不可", symbol: "×", available: false },
  "7": { text: "一般開放", symbol: "○", available: true },
  "8": { text: "予約済", symbol: "×", available: false },
  "9": { text: "仮予約", symbol: "×", available: false },
  "10": { text: "個人利用", symbol: "×", available: false },
};

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Access-Control-Max-Age": "86400",
};

/**
 * 日本時間 (JST) の基準日からの日付リスト (YYYY-MM-DD) を生成
 */
function getJSTDates(days = 30, offset = 0) {
  const now = new Date();
  const utc = now.getTime() + now.getTimezoneOffset() * 60000;
  const jstNow = new Date(utc + 3600000 * 9);

  const dates = [];
  for (let i = offset; i < offset + days; i++) {
    const d = new Date(jstNow.getTime() + i * 86400000);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    dates.push(`${yyyy}-${mm}-${dd}`);
  }
  return dates;
}

/**
 * 埼玉県の Direct API から特定日の空き枠を取得
 */
async function fetchDateSlots(targetDate, facilityId = 8, subFacilityIds = [268, 269, 270, 273, 274, 303, 304]) {
  const payload = {
    facilityId: facilityId,
    subFacilityIds: subFacilityIds,
    periodRange: "1",
    usageDate: targetDate,
  };

  const headers = {
    "Content-Type": "application/json",
    Referer: "https://saitama-pref-reserve.michi-shiru.jp/",
    Origin: "https://saitama-pref-reserve.michi-shiru.jp",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
  };

  try {
    const response = await fetch(TARGET_API_URL, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(payload),
    });

    if (response.ok) {
      const data = await response.json();
      return data?.result?.slots || [];
    }
    return [];
  } catch (err) {
    return [];
  }
}

/**
 * 取得した生データを整形・午前午後分類
 */
function formatSlots(rawSlots) {
  const seenKeys = new Set();
  const formatted = [];

  for (const slot of rawSlots) {
    const key = `${slot.subFacilityId}_${slot.targetDate}_${slot.slotStartTime}_${slot.slotEndTime}`;
    if (seenKeys.has(key)) continue;
    seenKeys.add(key);

    const startTime = slot.slotStartTime || "";
    const timeSlotType = startTime < "12:30:00" ? "午前" : "午後";
    const stInfo = STATUS_MAP[String(slot.slotStatus)] || { text: "不明", symbol: "?", available: false };

    formatted.push({
      subFacilityId: slot.subFacilityId,
      subFacilityName: slot.subFacilityName,
      timeSlotType: timeSlotType,
      date: slot.targetDate,
      startTime: slot.slotStartTime,
      endTime: slot.slotEndTime,
      status: slot.slotStatus,
      statusText: stInfo.text,
      symbol: stInfo.symbol,
      available: stInfo.available,
      lotteryAppNum: slot.lotteryAppNum || 0,
    });
  }

  formatted.sort((a, b) => {
    if (a.date !== b.date) return a.date.localeCompare(b.date);
    if (a.subFacilityName !== b.subFacilityName) return a.subFacilityName.localeCompare(b.subFacilityName);
    return a.startTime.localeCompare(b.startTime);
  });

  return formatted;
}

export default {
  async fetch(request, env, ctx) {
    // 1. CORS Preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS, status: 204 });
    }

    const url = new URL(request.url);

    // 2. 汎用 POST プロキシ (単一日または任意リクエストの中継用)
    if (url.pathname === "/proxy" && request.method === "POST") {
      try {
        const bodyText = await request.text();
        const headers = {
          "Content-Type": "application/json",
          Referer: "https://saitama-pref-reserve.michi-shiru.jp/",
          Origin: "https://saitama-pref-reserve.michi-shiru.jp",
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        };

        const apiRes = await fetch(TARGET_API_URL, {
          method: "POST",
          headers: headers,
          body: bodyText,
        });

        const resData = await apiRes.text();
        return new Response(resData, {
          status: apiRes.status,
          headers: {
            ...CORS_HEADERS,
            "Content-Type": "application/json",
          },
        });
      } catch (err) {
        return new Response(JSON.stringify({ error: String(err) }), {
          status: 500,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        });
      }
    }

    // 3. 秋ヶ瀬公園のオンタイム一括取得 API: GET / または GET /api/pref
    // サブリクエスト制限 (無料枠50件) を考慮し、days と offset で分割取得に対応 (デフォルト: days=30, offset=0)
    if (url.pathname === "/" || url.pathname === "/api/pref") {
      const days = Math.min(35, parseInt(url.searchParams.get("days") || "30", 10));
      const offset = parseInt(url.searchParams.get("offset") || "0", 10);

      const dates = getJSTDates(days, offset);

      // 指定日数をエッジから高速並行 fetch
      const slotArrays = await Promise.all(dates.map((d) => fetchDateSlots(d)));
      const rawSlots = slotArrays.flat();
      const formattedData = formatSlots(rawSlots);

      const now = new Date();
      const utc = now.getTime() + now.getTimezoneOffset() * 60000;
      const jstNow = new Date(utc + 3600000 * 9);
      const yyyy = jstNow.getFullYear();
      const mm = String(jstNow.getMonth() + 1).padStart(2, "0");
      const dd = String(jstNow.getDate()).padStart(2, "0");
      const hh = String(jstNow.getHours()).padStart(2, "0");
      const mi = String(jstNow.getMinutes()).padStart(2, "0");
      const ss = String(jstNow.getSeconds()).padStart(2, "0");
      const nowJSTStr = `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss} JST`;

      const result = {
        updatedAt: nowJSTStr,
        facilityName: "秋ヶ瀬公園",
        purposes: ["軟式野球", "ソフトボール"],
        totalSlots: formattedData.length,
        availableSlotsCount: formattedData.filter((s) => s.available).length,
        data: formattedData,
        _isLive: true,
        _offset: offset,
        _days: days,
      };

      return new Response(JSON.stringify(result), {
        status: 200,
        headers: {
          ...CORS_HEADERS,
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "public, max-age=30", // 30秒エッジキャッシュ
        },
      });
    }

    return new Response(JSON.stringify({ error: "Not Found" }), {
      status: 404,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  },
};
