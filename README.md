# newborn-diary-telegram-adapter

aiogram v3 Telegram bot that bridges the diary chat with `newborn_diary`.

## What it does

- **Parses new messages** from your wife's Telegram chat by forwarding them to `newborn_diary /events/from-text` and replies with a Russian confirmation.
- **Answers questions** via `/ask` command or any message starting with `?`.
- **Inline keyboard** (`/menu`) with one-tap quick actions: 🍼 Левая/Правая, 💧 Пописал, 💩 Покакал, 🚼 Подгузник, 😴 Заснул, 🌅 Проснулся, ❓ Спросить.

## Setup

```bash
# 1. Create a bot via @BotFather, get the token
# 2. Add the bot to your Telegram diary chat
# 3. Find the chat ID (e.g. via @userinfobot or Telegram API)

# 4. Configure settings
cp settings.dev.yml settings.yml  # then edit settings.yml for production
# Edit settings.dev.yml for development:
#   telegram.bot_token: "your-bot-token"
#   telegram.allowed_chat_ids: [-1001234567890]

# 5. Install deps
uv sync

# 6. Make sure newborn_diary is running (default http://localhost:8001)

# 7. Start the adapter
uv run fastapi dev --port 8002
```

## Configuration (`settings.dev.yml`)

```yaml
telegram:
  bot_token: "your-bot-token"
  allowed_chat_ids: [-1001234567890]   # list of chat IDs to process
  allowed_authors: ["Mila"]            # only parse messages from these authors

diary_api:
  base_url: http://localhost:8001
  request_timeout_sec: 60
```

- `allowed_chat_ids: []` — process messages from **all** chats (not recommended in production).
- `allowed_authors: []` — process messages from **all** authors in allowed chats.

## Usage in the chat

| Input | Action |
|---|---|
| Any plain text from an allowed author | Parsed via LLM, stored as events, replied with confirmation |
| `? <question>` | Answered via the QA service |
| `/ask <question>` | Same as above |
| `/menu` or `/start` | Shows inline keyboard |
| Tap inline button | Creates event immediately with current timestamp |

## Importing old messages from a Telegram topic

Telegram Desktop does not offer an export option inside a topic — the export must be done at the **chat level**, which includes all topics.

1. Open **Telegram Desktop** and go to the main chat (not inside any topic).
2. Click the three-dot menu (⋮) in the top right → **Export chat history**.
3. In the export dialog:
   - Uncheck all media types (photos, videos, etc.) — only text is needed.
   - Set the format to **Machine-readable JSON**.
   - Click **Export**.
4. Telegram Desktop saves the export as `result.json` in the folder you choose.
5. Import via the CLI (inside `newborn_diary/`):
   ```bash
   cd ../newborn_diary
   uv run python cli.py import-telegram-export /path/to/result.json
   ```
   Or via the API directly:
   ```bash
   curl -X POST http://localhost:8001/api/v1/admin/import/telegram-export \
     -F 'file=@/path/to/result.json'
   ```

The importer filters by the `parser.authors` list in `settings.dev.yml`, so only messages from the configured authors are processed regardless of which topic they came from. It also skips duplicates (matched by `source_message_id`), so re-running is safe.

## Tests

```bash
uv run pytest -s --ignore=tests/   # unit tests only (no network needed)
uv run pytest -s tests/            # integration tests
```
