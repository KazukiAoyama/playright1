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

const COURT_NAME_MAP = {
  629: "人工芝SSA",
  630: "人工芝SSB",
  631: "人工芝SSC",
  632: "天然芝SSD",
  633: "天然芝SSE",
};

function getCourtDisplayName(subId, rawName) {
  if (subId && COURT_NAME_MAP[subId]) return COURT_NAME_MAP[subId];
  if (rawName) {
    if (rawName.includes("人工芝第１") || rawName.includes("SSA")) return "人工芝SSA";
    if (rawName.includes("人工芝第２") || rawName.includes("SSB")) return "人工芝SSB";
    if (rawName.includes("人工芝第３") || rawName.includes("SSC")) return "人工芝SSC";
    if (rawName.includes("天然芝第１") || rawName.includes("SSD")) return "天然芝SSD";
    if (rawName.includes("天然芝第２") || rawName.includes("SSE")) return "天然芝SSE";
  }
  return rawName;
}

const DEFAULT_SUB_FACILITY_IDS = [268, 269, 270, 273, 274, 303, 304, 629, 630, 631, 632, 633];

/**
 * 埼玉県の Direct API から特定日の空き枠を取得
 */
async function fetchDateSlots(targetDate, facilityId = 8, subFacilityIds = DEFAULT_SUB_FACILITY_IDS) {
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
    const displayName = getCourtDisplayName(slot.subFacilityId, slot.subFacilityName);

    formatted.push({
      subFacilityId: slot.subFacilityId,
      subFacilityName: displayName,
      courtName: displayName,
      rawSubFacilityName: slot.subFacilityName,
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

    // 4. GitHub Actions ワークフロー手動キック用エンドポイント: /trigger-scrape
    if (url.pathname === "/trigger-scrape") {
      const force = url.searchParams.get("force") === "true";
      const result = await triggerGitHubWorkflow(env, { force });
      return new Response(JSON.stringify(result, null, 2), {
        status: result.success ? 200 : (result.status || 500),
        headers: {
          ...CORS_HEADERS,
          "Content-Type": "application/json; charset=utf-8",
        },
      });
    }

    // 5. 通知設定の取得: GET /api/notify-settings
    if (url.pathname === "/api/notify-settings" && request.method === "GET") {
      const result = await getNotifySettings(env);
      return new Response(JSON.stringify(result), {
        status: result.success ? 200 : 500,
        headers: {
          ...CORS_HEADERS,
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "no-cache",
        },
      });
    }

    // 6. 通知設定の保存: POST /api/notify-settings
    if (url.pathname === "/api/notify-settings" && request.method === "POST") {
      try {
        const body = await request.json();
        const result = await saveNotifySettings(env, body);
        return new Response(JSON.stringify(result), {
          status: result.success ? 200 : 500,
          headers: {
            ...CORS_HEADERS,
            "Content-Type": "application/json; charset=utf-8",
          },
        });
      } catch (err) {
        return new Response(JSON.stringify({ success: false, error: String(err) }), {
          status: 400,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        });
      }
    }

    // 7. LINEテスト通知送信: POST /api/test-notify
    if (url.pathname === "/api/test-notify" && request.method === "POST") {
      try {
        const body = await request.json().catch(() => ({}));
        const token = body.token || env.LINE_CHANNEL_ACCESS_TOKEN;
        const result = await sendLineBroadcast(token, body.message || "⚾ 【テスト通知】LINE通知設定が正常に保存され、接続テストに成功しました！");
        return new Response(JSON.stringify(result), {
          status: result.success ? 200 : 500,
          headers: {
            ...CORS_HEADERS,
            "Content-Type": "application/json; charset=utf-8",
          },
        });
      } catch (err) {
        return new Response(JSON.stringify({ success: false, error: String(err) }), {
          status: 400,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        });
      }
    }

    return new Response(JSON.stringify({ error: "Not Found" }), {
      status: 404,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  },

  /**
   * Cloudflare Cron Triggers により定刻に呼び出されるハンドラ
   */
  async scheduled(event, env, ctx) {
    console.log(`[Cron] Triggered at ${new Date().toISOString()}, cron: ${event.cron}`);
    ctx.waitUntil(
      triggerGitHubWorkflow(env, { force: false })
        .then((res) => {
          console.log("[Cron] Result:", JSON.stringify(res));
        })
        .catch((err) => {
          console.error("[Cron] Error executing triggerGitHubWorkflow:", err);
        })
    );
  },
};

/**
 * GitHub API 経由で Actions ワークフロー (workflow_dispatch) をキック
 */
async function triggerGitHubWorkflow(env, options = {}) {
  const owner = env.GITHUB_OWNER || "KazukiAoyama";
  const repo = env.GITHUB_REPO || "playright1";
  const workflowId = env.WORKFLOW_ID || "scrape.yml";
  const pat = env.GITHUB_PAT;

  if (!pat) {
    const msg = "GITHUB_PAT が設定されていません。wrangler secret put GITHUB_PAT で登録してください。";
    console.error(`[GitHub Trigger] ${msg}`);
    return { success: false, error: msg };
  }

  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowId}/dispatches`;
  const force = options.force === true;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${pat}`,
        "Accept": "application/vnd.github+json",
        "User-Agent": "Cloudflare-Worker-Scheduler",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          force: String(force),
        },
      }),
    });

    if (res.status === 204) {
      const msg = `Workflow (${workflowId}) triggered successfully! (force=${force})`;
      console.log(`[GitHub Trigger] ${msg}`);
      return { success: true, message: msg, timestamp: new Date().toISOString() };
    } else {
      const errorText = await res.text();
      console.error(`[GitHub Trigger] Failed: HTTP ${res.status}`, errorText);
      return {
        success: false,
        status: res.status,
        error: errorText,
      };
    }
  } catch (e) {
    console.error(`[GitHub Trigger] Exception:`, e);
    return { success: false, error: String(e) };
  }
}

/**
 * UTF-8文字列を安全にBase64エンコード
 */
function utf8ToBase64(str) {
  const bytes = new TextEncoder().encode(str);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/**
 * Base64文字列を安全にUTF-8デコード
 */
function base64ToUtf8(base64) {
  const binary = atob(base64.replace(/\r?\n/g, ""));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new TextDecoder().decode(bytes);
}

/**
 * GitHub API 経由で docs/notify_settings.json を取得
 */
async function getNotifySettings(env) {
  const owner = env.GITHUB_OWNER || "KazukiAoyama";
  const repo = env.GITHUB_REPO || "playright1";
  const pat = env.GITHUB_PAT;
  const path = "docs/notify_settings.json";

  const headers = {
    "User-Agent": "Cloudflare-Worker-NotifySettings",
    "Accept": "application/vnd.github+json",
  };
  if (pat) headers["Authorization"] = `Bearer ${pat}`;

  try {
    const res = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents/${path}`, { headers });
    if (!res.ok) {
      return { success: false, error: `GitHub API returned ${res.status}` };
    }
    const data = await res.json();
    const jsonStr = base64ToUtf8(data.content);
    const settings = JSON.parse(jsonStr);
    return { success: true, settings, sha: data.sha };
  } catch (e) {
    return { success: false, error: String(e) };
  }
}

/**
 * GitHub API 経由で docs/notify_settings.json を保存 (コミット)
 */
async function saveNotifySettings(env, settings) {
  const owner = env.GITHUB_OWNER || "KazukiAoyama";
  const repo = env.GITHUB_REPO || "playright1";
  const pat = env.GITHUB_PAT;
  const path = "docs/notify_settings.json";

  if (!pat) {
    return { success: false, error: "GITHUB_PAT が設定されていません。" };
  }

  const headers = {
    "User-Agent": "Cloudflare-Worker-NotifySettings",
    "Accept": "application/vnd.github+json",
    "Authorization": `Bearer ${pat}`,
  };

  try {
    // 既存ファイルの SHA を取得
    let sha = null;
    const getRes = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents/${path}`, { headers });
    if (getRes.ok) {
      const existing = await getRes.json();
      sha = existing.sha;
    }

    settings.updatedAt = new Date().toISOString();
    const contentStr = JSON.stringify(settings, null, 2);
    const base64Content = utf8ToBase64(contentStr);

    const body = {
      message: "update: LINE notification settings from web admin",
      content: base64Content,
    };
    if (sha) body.sha = sha;

    const putRes = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents/${path}`, {
      method: "PUT",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (putRes.ok || putRes.status === 201) {
      return { success: true, message: "Settings saved successfully", updatedAt: settings.updatedAt };
    } else {
      const errText = await putRes.text();
      return { success: false, error: errText, status: putRes.status };
    }
  } catch (e) {
    return { success: false, error: String(e) };
  }
}

/**
 * LINE Messaging API (Broadcast) へのメッセージ送信
 */
async function sendLineBroadcast(token, text) {
  if (!token) {
    return { success: false, error: "LINE Channel Access Token が指定されていません。" };
  }
  const url = "https://api.line.me/v2/bot/message/broadcast";
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`,
      },
      body: JSON.stringify({
        messages: [{ type: "text", text }],
      }),
    });
    if (res.ok) {
      return { success: true, message: "LINE broadcast sent successfully" };
    } else {
      const errText = await res.text();
      return { success: false, status: res.status, error: errText };
    }
  } catch (e) {
    return { success: false, error: String(e) };
  }
}


