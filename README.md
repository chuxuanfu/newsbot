# South Bay Newsbot

Personal 24/7 event radar for San Jose, Cupertino, Santa Clara, I-280, I-880,
CA-87, and US-101. It runs locally on a Mac Studio, stores data in SQLite, uses
Ollama by default for classification, and pushes high-priority alerts to one
Telegram bot chat.

## What It Monitors First

- CHP Bay Area traffic incidents
- NWS active alerts for San Jose
- USGS earthquakes
- CAL FIRE active incidents
- CA EDD WARN report
- State Department Visa Bulletin page
- Reddit public JSON feeds for local, immigration, and layoff subreddits
- San Jose Spotlight RSS

## Setup

Create a Telegram bot:

1. Open Telegram and message `@BotFather`.
2. Send `/newbot`.
3. Pick a display name.
4. Pick a username ending in `bot`.
5. Copy the token.
6. Send any message to your new bot.
7. Run:

```bash
curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
```

Find `message.chat.id` in the JSON response.

Create the local environment:

```bash
cd /Users/chuxuanfu/newsbot
PYTHON_BIN=/Users/chuxuanfu/.local/bin/python3 bash install.sh
. .venv/bin/activate
```

Edit `.env`:

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
OLLAMA_MODEL=llama3.1:8b
```

Make sure Ollama is running and the model exists:

```bash
ollama pull llama3.1:8b
ollama serve
```

In another terminal:

```bash
cd /Users/chuxuanfu/newsbot
. .venv/bin/activate
python -m app.main init-db
python -m app.main test-telegram
python -m app.main run-once
python -m app.main status
```

## 24/7 launchd

Fast path:

```bash
cd /Users/chuxuanfu/newsbot
./start_24_7.sh
```

Stop:

```bash
cd /Users/chuxuanfu/newsbot
./stop_24_7.sh
```

Manual setup:

Render the plist:

```bash
sed "s|__NEWSBOT_DIR__|/Users/chuxuanfu/newsbot|g" \
  launchd/com.chuxuanfu.newsbot.plist.template \
  > ~/Library/LaunchAgents/com.chuxuanfu.newsbot.plist
```

Load it:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.chuxuanfu.newsbot.plist
launchctl enable gui/$(id -u)/com.chuxuanfu.newsbot
launchctl kickstart -k gui/$(id -u)/com.chuxuanfu.newsbot
```

Logs:

```bash
tail -f /Users/chuxuanfu/newsbot/logs/newsbot.out.log
tail -f /Users/chuxuanfu/newsbot/logs/newsbot.err.log
```

Stop:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.chuxuanfu.newsbot.plist
```

## Commands

```bash
python -m app.main init-db
python -m app.main fetch
python -m app.main process
python -m app.main notify
python -m app.main digest
python -m app.main run-once
python -m app.main daemon
python -m app.main test-telegram
python -m app.main status
```

## Switching To OpenAI

Edit `config.yaml`:

```yaml
classifier:
  provider: openai
```

Then set `.env`:

```bash
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1-mini
```

## Notes

- Telegram uses one bot and one chat only.
- Low-confidence items go into the local database and digest, not immediate alerts.
- Reddit public JSON can be rate-limited or blocked. The fetcher records failures
  in `source_state` instead of crashing the daemon.
- The bot does not log into Nextdoor, Facebook, X, Discord, or WeChat.
