# South Bay Newsbot

Personal 24/7 event radar for San Jose, Cupertino, Santa Clara, I-280, I-880,
CA-87, and US-101. It runs locally, stores data in SQLite, uses Ollama by
default for Chinese summaries/classification, and sends alerts to one Telegram
bot chat.

## What It Monitors

- CHP Bay Area traffic incidents, filtered to the configured South Bay radius
- NWS active weather alerts near San Jose
- USGS earthquakes near San Jose, filtered by distance and magnitude
- CAL FIRE active incidents
- CA EDD WARN report
- State Department Visa Bulletin page
- Reddit public feeds for local, immigration, and layoff subreddits
- Bay Area local news RSS feeds

See `SOURCES.md` for the source inventory and operational notes.

## Requirements

- macOS for the provided 24/7 `launchd` service scripts
- Git
- Python 3.11 or newer
- Telegram account
- Ollama, if using local AI summaries
- Optional: OpenAI API key, only if you enable OpenAI fallback/provider

Install common prerequisites on macOS:

```bash
xcode-select --install
brew install python git ollama
```

If you do not use Homebrew, install Python from `https://www.python.org/` and
Ollama from `https://ollama.com/`.

## 1. Clone The Project

```bash
git clone git@github.com:chuxuanfu/newsbot.git
cd newsbot
```

If SSH is not configured for GitHub, use HTTPS instead:

```bash
git clone https://github.com/chuxuanfu/newsbot.git
cd newsbot
```

## 2. Install Python Dependencies

```bash
bash install.sh
```

This creates:

- `.venv/` for Python packages
- `.env` copied from `.env.example`
- `data/newsbot.sqlite3`
- `data/maps/`
- `logs/`

If `python3` is not on your `PATH`, provide it explicitly:

```bash
PYTHON_BIN=/absolute/path/to/python3 bash install.sh
```

If Python is missing entirely, install Python 3.11+ first. On macOS with
Homebrew:

```bash
brew install python
```

## 3. Create A Telegram Bot

1. Open Telegram.
2. Message `@BotFather`.
3. Send `/newbot`.
4. Pick a display name.
5. Pick a username ending in `bot`.
6. Copy the token BotFather gives you.
7. Send any message to your new bot from the Telegram account or group that
   should receive alerts.

Find your chat id:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
```

In the JSON output, find:

```json
"chat": {
  "id": 123456789
}
```

For a group chat, the id is often negative, for example `-1001234567890`.

## 4. Configure `.env`

Open `.env` and fill in:

```bash
TELEGRAM_BOT_TOKEN=replace_with_your_bot_token
TELEGRAM_CHAT_ID=replace_with_your_chat_id
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.6:27b
```

Do not commit `.env`. It is ignored by Git.

`NEWSBOT_CONFIG` and `NEWSBOT_DB` are optional. If you leave them unset, the app
uses:

```text
config.yaml
data/newsbot.sqlite3
```

inside the cloned project directory.

## 5. Set Up Ollama

Start Ollama:

```bash
ollama serve
```

In another terminal, pull the configured model:

```bash
ollama pull qwen3.6:27b
```

If your machine cannot run that model comfortably, choose a smaller Ollama model
and set the same value in `.env`, for example:

```bash
OLLAMA_MODEL=qwen2.5:7b
```

The app asks Ollama to disable thinking output where supported, and strips
`<think>...</think>` blocks as a fallback.

## 6. Test The Bot Manually

```bash
cd newsbot
. .venv/bin/activate
python -m app.main test-telegram
python -m app.main run-once
python -m app.main status
```

Expected result:

- `test-telegram` sends a test message to Telegram.
- `run-once` fetches sources, writes new items to SQLite, and sends eligible
  notifications.
- `status` prints source state, raw item counts, event counts, and notification
  counts.

## 7. Run 24/7 On macOS

Start or restart the background service:

```bash
cd newsbot
./start_24_7.sh
```

The script installs a LaunchAgent at:

```text
~/Library/LaunchAgents/com.chuxuanfu.newsbot.plist
```

and starts:

```bash
.venv/bin/python -m app.main daemon
```

Stop it:

```bash
cd newsbot
./stop_24_7.sh
```

Check whether it is running:

```bash
launchctl print gui/$(id -u)/com.chuxuanfu.newsbot | grep -E "state =|pid ="
```

Watch logs:

```bash
tail -f logs/newsbot.err.log
tail -f logs/newsbot.out.log
```

## 8. Manual Commands

Run these from the project directory after activating the virtualenv:

```bash
. .venv/bin/activate

python -m app.main init-db
python -m app.main fetch
python -m app.main process
python -m app.main notify
python -m app.main digest
python -m app.main backfill-rss --limit-per-source 2
python -m app.main run-once
python -m app.main daemon
python -m app.main test-telegram
python -m app.main status
```

## 9. Configuration

Most behavior is controlled by `config.yaml`:

- `runtime.poll_sleep_seconds`: daemon loop sleep
- `runtime.process_batch_size`: AI items processed per loop
- `runtime.reddit_request_delay_seconds`: delay between Reddit requests
- `locations.center`: center point for distance filters
- `locations.chp_report_radius_miles`: CHP report radius
- `sources`: fetch source definitions and intervals
- `notifications.notify_on_first_fetch`: whether first fetch should notify
- `notifications.rss_max_age_hours`: max RSS/local-news article age to notify

After changing `config.yaml` or `.env`, restart the service:

```bash
./start_24_7.sh
```

## 10. Switching To OpenAI

Ollama is the default. To use OpenAI, edit `config.yaml`:

```yaml
classifier:
  provider: openai
```

Then set `.env`:

```bash
OPENAI_API_KEY=replace_with_your_key
OPENAI_MODEL=gpt-4.1-mini
```

Restart the service after changing providers.

## 11. Privacy And Git Safety

The repository intentionally ignores local runtime and secret files:

- `.env`
- `.venv/`
- `data/`
- `logs/`
- `.obsidian/`
- SQLite database files
- Python cache directories

Before pushing changes, check:

```bash
git status --short
git diff --cached --name-only
```

Never commit a real Telegram bot token, chat id, OpenAI API key, database, or
log file.

## 12. Troubleshooting

Telegram test fails:

- Check `TELEGRAM_BOT_TOKEN`.
- Check `TELEGRAM_CHAT_ID`.
- Send a message to the bot first, then rerun `getUpdates`.

Ollama fails:

- Make sure `ollama serve` is running.
- Make sure `ollama pull <model>` has completed.
- Use a smaller model if your machine is memory constrained.

No new notifications:

- Run `python -m app.main status`.
- Check `logs/newsbot.err.log`.
- The first fetch may create a baseline without notifying.
- RSS/local-news articles older than `rss_max_age_hours` are skipped.
- CHP and USGS items may be filtered by distance or magnitude.

Reddit is rate-limited:

- Increase Reddit source intervals in `config.yaml`.
- Increase `runtime.reddit_request_delay_seconds`.
- Reduce the number of Reddit sources.

CHP map/geocoding fails:

- Confirm the machine has network access.
- Check `logs/newsbot.err.log`.
- The app uses OpenStreetMap/Nominatim for geocoding and map tiles.

## 13. More Documentation

- `SOP.md`: full structured operating procedure
- `SOURCES.md`: source list, limits, and paid/free source notes
