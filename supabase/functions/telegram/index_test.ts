import { handler } from "./index.ts";

Deno.test("rejects forged webhooks and ignores group Start", async () => {
  Deno.env.set("TELEGRAM_WEBHOOK_SECRET", "webhook-test");
  const make = (secret: string, type: string) => new Request("https://example.test/telegram/webhook", {
    method: "POST",
    headers: { "X-Telegram-Bot-Api-Secret-Token": secret },
    body: JSON.stringify({ message: { text: "/start " + "a".repeat(64),
      chat: { id: 101, type }, from: { id: 101 } } }),
  });
  if ((await handler(make("wrong", "private"))).status !== 401) throw new Error("Accepted forged webhook");
  if ((await handler(make("webhook-test", "group"))).status !== 200) throw new Error("Group Start reached the database");
  if ((await handler(new Request("https://example.test/telegram", { method: "POST" }))).status !== 401) {
    throw new Error("Accepted unauthenticated installation");
  }
});
