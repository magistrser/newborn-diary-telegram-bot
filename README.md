# telegram_adapter

aiogram v3 Telegram bot that bridges a family Telegram chat with `newborn_diary`.

---

## Overview

The adapter listens to a Telegram chat. Incoming text messages from allowed authors are forwarded
to `newborn_diary` for parsing; the parsed events are echoed back as a confirmation with an inline
keyboard for immediate correction. Questions (prefixed with `?` or via `/ask`) are answered by the
QA service. A retry queue persists failed API calls to Postgres and re-attempts them automatically.

---

## Requirements

- Python 3.14.3 (`uv` manages the venv)
- PostgreSQL (for FSM state storage and the retry queue)
- `newborn_diary` running (default `http://localhost:8001`)
- Telegram bot token from @BotFather

---

## Quick start

```bash
# 1. Create settings (copy and edit)
cp settings.dev.yml.example settings.dev.yml
# Fill in: telegram.bot_token, telegram.allowed_chat_ids, postgres.*

# 2. Install deps
uv sync

# 3. Make sure newborn_diary is running at diary_api.base_url

# 4. Start the adapter (dev mode, port 8002)
uv run fastapi dev --port 8002
```

The adapter creates its Postgres database automatically at startup if it does not exist.
No manual migration step is needed — tables are created via `SqlFsmStorage` and
`SqlPendingActionsRepository` on first run.

---

## Configuration (`settings.dev.yml`)

```yaml
telegram:
  bot_token: "your-bot-token"
  allowed_chat_ids: [-1001234567890]   # empty list = allow all chats (not for production)
  allowed_authors: ["Mila"]            # empty list = allow all authors in allowed chats
  event_topic_id: null                 # forum topic ID for diary events; null = any topic
  question_topic_id: null              # forum topic ID for questions; null = any topic

diary_api:
  base_url: http://localhost:8001
  request_timeout_sec: 660             # long: LLM parsing can take 10–30 s locally

postgres:
  host: localhost
  port: 5432
  db_name: telegram_adapter
  user: adapter
  password: adapter
  pool_size: 5

retry:
  interval_min: 10   # how often the retry loop fires (minutes)
```

`ENVIRONMENT` env var selects the settings file:
- `DEVELOPMENT` / unset → `settings.dev.yml`
- `TEST` → `settings.test.yml`
- `PRODUCTION` → `settings.yml`

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (returns 200 if bot is running) |
| GET | `/metrics` | Prometheus metrics |

The bot itself uses Telegram long-polling, not webhooks. FastAPI is only there for health and
metrics. Uvicorn owns the event loop; the bot's polling runs as a background `asyncio.Task`.

---

## Usage in the chat

| Input | Action |
|-------|--------|
| Any plain text from an allowed author | Parsed via LLM, stored as events, reply with confirmation + inline keyboard |
| `? <question>` | Answered via the QA service |
| `/ask <question>` | Same as above |
| `/ask` (no argument) | Enters ask mode: next text message becomes the question |
| `/menu` or `/start` | Shows sectioned inline keyboard |
| Tap quick-action button | Creates event immediately with current UTC timestamp |

For Telegram groups with forum topics enabled, set `telegram.event_topic_id` to the topic whose
plain text should be parsed as diary events, and `telegram.question_topic_id` to the topic where
plain text, `?`, and `/ask` questions are accepted and answered. Leaving either value `null`
preserves the previous behavior for that route: all topics are accepted.

The `diary_api.request_timeout_sec` default (660 s) is intentionally high because local LLM
inference for a single message can take 10–30 seconds depending on the model size.

---

## Architecture

```
telegram_adapter/
├── domain/
│   ├── pending_action.py          — retry action model
│   ├── policies.py                — access policy + compatible payload merge rules
│   └── quick_actions.py           — quick-action command definitions
├── application/
│   ├── ports.py                   — diary API and pending-action repository ports
│   └── services/
│       └── action_retry_queue.py   — persistent retry queue orchestration
├── infrastructure/
│   ├── composition.py             — FastAPI/client/retry-queue composition root
│   ├── diary_api_client.py        — async httpx client wrapping newborn_diary endpoints
│   ├── telegram/
│   │   ├── handlers.py             — all aiogram message / callback handlers + FSM states
│   │   ├── keyboards.py            — inline keyboard builders + ACTION_MAP
│   │   └── runner.py               — starts polling task + retry queue; handles graceful shutdown
│   ├── endpoints/
│   │   ├── health_check.py
│   │   └── get_metrics.py
│   ├── models/
│   │   ├── fsm_state.py            — SQLAlchemy model for aiogram FSM storage
│   │   └── pending_action.py       — SQLAlchemy model for pending retry actions
│   ├── repositories/
│   │   ├── fsm_state_storage.py    — aiogram BaseStorage backed by Postgres
│   │   └── pending_action_repository.py — CRUD for pending_actions table
│   └── metrics/
├── settings.py   — Pydantic settings from YAML
└── main.py       — FastAPI app + lifespan (starts/stops runner)
```

---

## Telegram bot features

### Free-text message handling

1. `_is_allowed(chat_id, author)` gates every message.
2. If `question_topic_id` is configured, any text in that topic is routed to the QA path.
3. Messages starting with `?` are routed to the QA path when they match `question_topic_id`, or in
   any topic when `question_topic_id` is not configured.
4. All other text is ignored unless it matches `event_topic_id`, then POSTed to
   `diary_api /api/v1/events/from-text` with the Telegram message ID
   and chat ID. The response events are formatted in Russian and sent as a reply with the
   **event summary keyboard**.
5. On API failure the message is enqueued in the retry queue; user sees a warning reply.

### Quick-action keyboard (`/menu` or `/start`)

`QUICK_ACTIONS` in `keyboards.py` defines all buttons. Each entry is
`(callback_id, label, event_type, payload)`. Section headers are non-clickable `noop` buttons.
The layout is 2 buttons per row inside each section.

Tapping a quick-action button POSTs directly to `diary_api /api/v1/events` with `occurred_at = now()`.

### Event summary keyboard (after parsing)

After a message is parsed, the reply includes an inline keyboard with one row per event:

```
[ 🕒 HH:MM ]  [ 🔀 ]  [ 🗑 ]
[ ✅ Готово ]
```

- `🕒 HH:MM` — enter time-edit mode (FSM `EditState.waiting_for_new_time`)
- `🔀` — switch to type-change sub-keyboard
- `🗑` — delete this event via `DELETE /api/v1/events/{id}`
- `✅ Готово` — dismiss (deletes the summary message, clears FSM cache)

Parsed events are cached in aiogram FSM state keyed by the **summary message ID**
(`state_data[str(summary_message_id)] = [event_dicts]`). FSM state is stored in Postgres.

### Time editing (FSM)

`ev_tm:<event_id>` → sets `EditState.waiting_for_new_time`. The next text message matching
`\d{1,2}:\d{2}` is parsed, combined with the event's original date (Moscow tz), and sent as
`PATCH /api/v1/events/{id}` with the new `occurred_at`. The prompt message is deleted and the
summary message is edited in place.

### Type changing

`ev_tp:<event_id>` replaces the summary keyboard with `type_change_keyboard(event_id)` — a
sectioned sub-keyboard identical to the main keyboard. Selecting a type sends
`ev_sub:<event_id>:<action_id>`, which:

1. GETs the current event from the API.
2. Merges `_COMMON_FIELDS` (`duration_min`) from the old payload into the new preset payload.
3. PATCHes the event with the new type and merged payload.
4. Updates FSM cache and re-renders the summary message.

`ev_back:<event_id>` returns to the event summary keyboard.

---

## Action retry queue (`application/services/action_retry_queue.py`)

Handles transient failures when `newborn_diary` is temporarily unreachable.

- `ActionRetryQueue` keeps failed actions in memory (`dict[id, PendingAction]`) and persists them
  to Postgres via `SqlPendingActionsRepository`.
- On startup, `initialize()` calls `repo.setup()` (creates table if missing) then loads all
  previously queued actions so they survive adapter restarts.
- A background `asyncio.Task` wakes every `retry_interval_min` minutes and calls `retry_once()`.
- `retry_once()` attempts every pending action once; succeeded items are removed from memory and DB.
- Two action types: `parse_text` and `create_event`.
- `attempt_count` is incremented on each retry and persisted; no automatic give-up (manual
  intervention needed for permanently broken actions).
- The queue is exposed as a process-level singleton via `set_retry_queue` / `get_retry_queue`.
  Handlers call `get_retry_queue()` at call time (not at import time) to avoid the
  initialisation-order problem.

---

## Database schema (Postgres, auto-created)

### `fsm_states`

Stores aiogram FSM state per `(chat_id, user_id, bot_id)` key. JSON column holds both the state
name and the state data dict. Managed by `SqlFsmStorage`.

### `pending_actions`

```
id          TEXT PRIMARY KEY
action_type TEXT          -- 'parse_text' | 'create_event'
created_at  TEXT          -- ISO-8601
attempt_count INTEGER
text, occurred_at, source_type, source_message_id, source_chat_id  -- parse_text fields
event_type, payload_json  -- create_event fields
```

Created by `SqlPendingActionsRepository.setup()` using raw `CREATE TABLE IF NOT EXISTS`.

---

## Graceful shutdown

The lifespan in `main.py` calls `stop_polling()` on shutdown:

1. Stops the retry queue task.
2. **Closes the bot's HTTP session first** (`await bot.session.close()`). This aborts the active
   long-poll request to Telegram immediately. Without this, aiogram's own cleanup blocks waiting
   for the request to finish.
3. Cancels the polling task and waits up to 5 seconds using `asyncio.wait` (not `asyncio.wait_for`)
   because `wait_for` in Python 3.12+ waits for cancelled tasks' finally blocks, which can hang if
   aiogram makes slow network calls.
4. Disposes the SQLAlchemy engine.

`handle_signals=False` is passed to `dp.start_polling()` so aiogram does not install its own signal
handlers — uvicorn owns signal handling.

`skip_updates=False` is intentional: the bot processes updates that arrived while it was offline.

---

## DiaryApiClient (`infrastructure/diary_api_client.py`)

Thin async httpx wrapper around `newborn_diary`. Every call opens a new `httpx.AsyncClient` and
closes it on completion. Methods:

| Method | Endpoint |
|--------|----------|
| `parse_text(...)` | POST `/api/v1/events/from-text` |
| `create_event(...)` | POST `/api/v1/events` |
| `get_event(id)` | GET `/api/v1/events/{id}` |
| `update_event(id, ...)` | PATCH `/api/v1/events/{id}` |
| `delete_event(id)` | DELETE `/api/v1/events/{id}` |
| `ask(question)` | POST `/api/v1/ask` |

All methods raise `httpx.HTTPStatusError` on non-2xx responses; handlers catch generic `Exception`.

---

## Hacks and non-obvious decisions

- **New httpx client per call**: avoids connection-pool lifetime management. The number of
  concurrent requests is low (diary parsing is sequential per message), so overhead is negligible.

- **FSM state in Postgres**: the default aiogram memory storage would lose all state on restart.
  Postgres storage means time-edit and type-change flows survive a redeploy mid-conversation.

- **Summary events cached in FSM state by summary message ID**: the bot does not query the API on
  every button press. After parsing, events are stored in `state_data[str(msg_id)]`. This means
  if the bot restarts between the parse reply and the user tapping a button, the inline keyboard
  stops working (the FSM data is there but the in-memory cache is gone — actually FSM is persisted,
  so this should work). The cache is cleaned up on `ev_done`.

- **`_COMMON_FIELDS = {'duration_min'}`**: when changing event type via inline keyboard, fields
  listed here are carried over from the old payload to the new one. This preserves e.g. "20 min"
  when the user corrects `sleep_end` to `tummy_time`.

- **`_safe_answer`**: Telegram callback queries expire after ~10 minutes. Calling `query.answer()`
  on a stale callback raises an exception that is swallowed silently. Without this, a user tapping
  a button on an old message would cause an unhandled exception.

- **`_ensure_database_exists`**: at startup, runner connects to the Postgres `postgres` database
  and creates the adapter DB if absent. Saves a manual step when deploying from scratch.

- **Bot starts with `parse_mode=ParseMode.HTML`** (DefaultBotProperties). All confirmation text
  must be HTML-safe. `_handle_question` uses `html.escape(answer)` to prevent injection from the
  LLM answer.

- **`allowed_chat_ids: []` = allow all**: empty list is falsy, so the `_is_allowed` check short-
  circuits to `True`. Same for `allowed_authors`.

---

## Tests

```bash
# Unit tests (no DB, no network)
uv run pytest -s --ignore=tests/

# Integration tests (require Postgres)
uv run pytest -s tests/
```
