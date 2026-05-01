export default async function handler(req, res) {
  const { id, type, ts } = req.query;
  const ip = req.headers["x-forwarded-for"] || "unknown";
  const ua = req.headers["user-agent"] || "unknown";

  const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
  const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;

  // Anti-prefetch: ignore si appelé moins de 30s après l'envoi
  const now = Math.floor(Date.now() / 1000);
  const sentAt = parseInt(ts || "0");
  const delay = now - sentAt;

  if (sentAt > 0 && delay < 30) {
    console.log(`[PREFETCH ignoré] ${id} — délai: ${delay}s`);
    const pixel = Buffer.from(
      "R0lGODlhAQABAPAAAAAAAAAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==",
      "base64"
    );
    res.setHeader("Content-Type", "image/gif");
    res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate");
    return res.status(200).send(pixel);
  }

  try {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: TELEGRAM_CHAT_ID,
        parse_mode: "HTML",
        text: `🔥 <b>Email ouvert!</b>\n\n📧 ${id}\n📬 ${type || "first"}\n⏰ ${new Date().toLocaleString("fr-FR", { timeZone: "Europe/Paris" })}`,
      }),
    });
  } catch (e) {
    console.error("Telegram error:", e);
  }

  const pixel = Buffer.from(
    "R0lGODlhAQABAPAAAAAAAAAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==",
    "base64"
  );
  res.setHeader("Content-Type", "image/gif");
  res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate");
  res.status(200).send(pixel);
}
