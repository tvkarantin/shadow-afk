const env = (name: string) => Deno.env.get(name) || "";
const project = env("SUPABASE_URL");
const service = env("SUPABASE_SERVICE_ROLE_KEY");
const encoder = new TextEncoder();

async function digest(value: string) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}
async function secretMatches(actual: string | null, expected: string) {
  if (!actual || !expected) return false;
  const [a, b] = await Promise.all([digest(actual), digest(expected)]);
  return a.reduce((diff, value, i) => diff | (value ^ b[i]), 0) === 0;
}
function hex(bytes: Uint8Array) {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}
async function rpc(name: string, payload: object) {
  const response = await fetch(project + "/rest/v1/rpc/" + name, {
    method: "POST",
    headers: { apikey: service, Authorization: "Bearer " + service, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error("database_unavailable");
  return await response.json();
}

async function deliver(owner: string | null, limit: number) {
  const token = env("TELEGRAM_BOT_TOKEN");
  if (!token) throw new Error("bot_unconfigured");
  const notices = await rpc("telegram_claim", { p_owner: owner, p_limit: limit });
  let failed = 0;
  await Promise.all(notices.map(async (notice: { chat_id: number; message: string }) => {
    try {
      const response = await fetch("https://api.telegram.org/bot" + token + "/sendMessage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: notice.chat_id, text: notice.message }),
        signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) failed++;
      await response.body?.cancel();
    } catch {
      failed++;
    }
  }));
  // Do not retry ambiguous sends. Telegram has no idempotency key for sendMessage.
  return failed;
}

const json = (body: object, status = 200) =>
  Response.json(body, { status, headers: { "Cache-Control": "no-store" } });

export async function handler(request: Request) {
  if (request.method !== "POST") return json({ error: "method" }, 405);
  const route = new URL(request.url).pathname.split("/").pop();
  try {
    if (route === "webhook") {
      if (!await secretMatches(request.headers.get("X-Telegram-Bot-Api-Secret-Token"), env("TELEGRAM_WEBHOOK_SECRET"))) {
        return json({ error: "unauthorized" }, 401);
      }
      const { message } = await request.json();
      const start = /^\/start ([a-f0-9]{64})$/.exec(message?.text ?? "");
      if (start && message.chat?.type === "private" && Number.isSafeInteger(message.chat.id) &&
          message.chat.id > 0 && message.from?.id === message.chat.id && !message.from.is_bot) {
        const name = [message.from.first_name, message.from.last_name].filter(Boolean).join(" ") ||
          message.from.username || "Telegram";
        const linked = await rpc("telegram_confirm", {
          p_hash: hex(await digest(start[1])), p_chat: message.chat.id, p_name: name,
        });
        if (linked && await deliver(linked, 10)) console.warn("Telegram delivery failed");
      }
      return json({ ok: true });
    }
    if (route === "cron") {
      if (!await secretMatches(request.headers.get("X-Shadow-Cron-Secret"), env("SHADOW_CRON_SECRET"))) {
        return json({ error: "unauthorized" }, 401);
      }
      await rpc("telegram_sweep", {});
      if (await deliver(null, 20)) console.warn("Telegram delivery failed");
      return json({ ok: true });
    }
    if (route !== "telegram") return json({ error: "route" }, 404);
    const authorization = request.headers.get("Authorization");
    if (!authorization?.startsWith("Bearer ")) return json({ error: "unauthorized" }, 401);
    const auth = await fetch(project + "/auth/v1/user", {
      headers: { apikey: service, Authorization: authorization }, signal: AbortSignal.timeout(8000),
    });
    if (auth.status === 401 || auth.status === 403) return json({ error: "unauthorized" }, 401);
    if (!auth.ok) throw new Error("auth_unavailable");
    const user = await auth.json();
    if (!user.id || user.is_anonymous !== true) return json({ error: "unauthorized" }, 401);
    const data = await request.json();
    const action = data.action;
    if (!["begin", "cancel", "unlink", "heartbeat", "preferences", "notify", "status"].includes(action)) {
      return json({ error: "action" }, 400);
    }
    let link: string | undefined;
    let payload: object = {};
    if (action === "begin") {
      const bot = env("TELEGRAM_BOT_USERNAME");
      if (!/^[A-Za-z][A-Za-z0-9_]{4,31}$/.test(bot) || !env("TELEGRAM_BOT_TOKEN")) {
        return json({ error: "bot_unconfigured" }, 503);
      }
      const token = hex(crypto.getRandomValues(new Uint8Array(32)));
      payload = { hash: hex(await digest(token)) };
      link = "https://t.me/" + bot + "?start=" + token;
    } else if (action === "preferences") {
      if (!Array.isArray(data.events) || data.events.length > 6 ||
          data.events.some((item: unknown) => typeof item !== "string" || item.length > 32)) {
        return json({ error: "events" }, 400);
      }
      payload = { events: data.events };
    } else if (action === "notify") {
      if (!/^(test|victory|recognition|fortnite_exit|app_error|summary)$/.test(data.event) ||
          typeof data.key !== "string" || !/^[a-zA-Z0-9:_-]{1,120}$/.test(data.key) ||
          typeof data.binding !== "string") return json({ error: "event" }, 400);
      const stats = [data.games, data.completed, data.seconds];
      if (data.event === "summary" && stats.some((n) => !Number.isSafeInteger(n) || n < 0 || n > 2_000_000_000)) {
        return json({ error: "stats" }, 400);
      }
      payload = { ...data, key: data.event + ":" + data.key };
    }
    const result = await rpc("telegram_device", { p_owner: user.id, p_action: action, p_data: payload });
    if (result.error) return json(result, result.error === "rate_limited" ? 429 : 409);
    if (action === "notify" && await deliver(user.id, 10)) return json({ error: "delivery_failed" }, 502);
    return json({ ...result, ...(link ? { link } : {}) });
  } catch {
    return json({ error: "service_unavailable" }, 503);
  }
}

if (import.meta.main) Deno.serve(handler);
