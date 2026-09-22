# black-velvet-bot

Config is hardcoded in `app/config.py`. No `.env` is needed.

```bash
docker build -t black-velvet-bot .
docker run -d --name black-velvet-bot -p 8033:8033 black-velvet-bot
```

The process listens on `POST /webhook` and always returns HTTP 200. It does not call `setWebhook`. Bot replies go to the hardcoded group id. Commands like `/register@BlackVelvetDatingBot` work. `!ping` sends a welcome message to that group.

SQLite lives at `/app/data/bot.db` inside the same container.
