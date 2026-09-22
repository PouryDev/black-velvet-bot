# black-velvet-bot

Telegram group match bot. Fills `.env` from `.env.example`, then:

```bash
docker build -t black-velvet-bot .
docker run --env-file .env -p 8033:8033 black-velvet-bot
```

`WEBHOOK_URL` must be the public HTTPS URL that reaches `POST /webhook` on port 8033. All Telegram Bot API calls go through `TELEGRAM_API_BASE`. SQLite lives at `DB_PATH` inside the same container (`/app/data/bot.db`).
