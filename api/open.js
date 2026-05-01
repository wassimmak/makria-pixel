const BOT_UA = [
  "microsoft office", "outlook", "office", "preview",
  "bot", "crawler", "spider", "fetch", "curl",
  "python", "java", "ruby", "wget", "libwww",
  "googleimageproxy", "googlebot", "yahoo", "bing",
  "apple mail", "thunderbird", "lotus", "evolution",
  "yahoo mail", "proofpoint", "barracuda", "mimecast"
];

// UA trop courts ou génériques = prefetch déguisé (ex: Outlook "Mozilla/5.0")
function isPrefetch(ua) {
  const lower = (ua || "").toLowerCase();
  if (BOT_UA.some(bot => lower.includes(bot))) return true;
  // UA trop court = prefetch déguisé (vrai browser a toujours > 50 chars)
  if (ua.length < 50) return true;
  return false;
}

export default async function handler(req, res) {
  const { id, type } = req.query;
  const ua = req.headers["user-agent"] || "";

  const pixel = Buffer.from(
    "R0lGODlhAQABAPAAAAAAAAAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==",
    "base64"
  );
  res.setHeader("Content-Type", "image/gif");
  res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate");

  // Log TOUS les appels pour débug
  console.log(`[PIXEL] id=${id} | UA=${ua} | prefetch=${isPrefetch(ua)}`);

  // Filtre prefetch par User-Agent
  if (isPrefetch(ua)) {
    console.log(`[IGNORÉ] prefetch détecté`);
    return res.status(200).send(pixel);
  }

  const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
  const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;

  try {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: TELEGRAM_CHAT_ID,
        parse_mode: "HTML",
        text: `🔥 <b>Email ouvert!</b>\n\n📧 ${id}\n📬 ${type || "first"}\n🖥️ <code>${ua.substring(0, 80)}</code>\n⏰ ${new Date().toLocaleString("fr-FR", { timeZone: "Europe/Paris" })}`,
      }),
    });
  } catch (e) {
    console.error("Telegram error:", e);
  }

  return res.status(200).send(pixel);
}
