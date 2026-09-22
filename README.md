# black-velvet-bot

Telegram group match bot. Copy `.env.example` to `.env`, set `BOT_TOKEN` and `ALLOWED_GROUP_ID`, then:

```bash
docker build -t black-velvet-bot .
docker run -d --name black-velvet-bot --env-file .env -p 8033:8033 black-velvet-bot
```

The process stays up and listens on `POST /webhook`. It does **not** call `setWebhook`; point Telegram at your public HTTPS URL yourself (through `TELEGRAM_API_BASE` if you use the Cloudflare worker). If you set `WEBHOOK_SECRET`, send the same secret when you set the webhook.

SQLite lives at `DB_PATH` inside the same container (`/app/data/bot.db`).
