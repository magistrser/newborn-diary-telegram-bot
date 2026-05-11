# Telegram Bot Setup

## Step 1 — Create the bot via BotFather

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot`.
3. Enter a display name, e.g. `Newborn Diary`.
4. Enter a username (must end in `bot`), e.g. `newborn_diary_bot`.
5. BotFather replies with a token like:
   ```
   5123456789:AAF_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
   **Copy it — you will need it in Step 3.**
6. In @BotFather:
   ```
   /setprivacy
   ```
Choose your bot → Disable.

## Step 2 — Add the bot to your diary chat

1. Open the Telegram group/chat where your wife posts diary messages.
2. Tap the chat name at the top → **Add members** → search for your bot username → **Add**.
3. If the chat is a group, promote the bot to **Admin** so it can read all messages:
   - Chat settings → Administrators → Add Administrator → select the bot → enable **Read messages** (other permissions can stay off).

> **Private chat:** if you prefer a private chat with the bot instead of adding it to the group, skip the admin step. The bot receives all messages sent directly to it.

## Step 3 — Find the chat ID

The bot needs the numeric chat ID to filter which chats it processes.

**Option A — use @userinfobot (easiest)**

1. Add **@userinfobot** to the same chat.
2. It will immediately print the chat ID, e.g. `-1001234567890`.
3. Remove @userinfobot from the chat.

**Option B — via Telegram API**

1. Send any message to the chat after adding your bot.
2. Open this URL in a browser (replace `TOKEN` with your bot token):
   ```
   https://api.telegram.org/botTOKEN/getUpdates
   ```
3. Find `"chat":{"id": -1001234567890, ...}` in the JSON response.

## Step 4 — Configure the adapter

Edit `settings.dev.yml` (development) or `settings.yml` (production):

```yaml
telegram:
  bot_token: "5123456789:AAF_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  allowed_chat_ids:
    - -1001234567890        # the chat ID from Step 3
  allowed_authors:
    - Mila                  # Telegram display name(s) whose messages are auto-parsed
                            # Leave empty [] to process messages from ALL chat members
  event_topic_id: null      # Forum topic ID for diary events; null = any topic
  question_topic_id: null   # Forum topic ID for questions; null = any topic

diary_api:
  base_url: http://localhost:8001   # URL of the running newborn_diary
  request_timeout_sec: 60
```

> `settings.yml` is gitignored and used in production (`ENVIRONMENT=PRODUCTION`).  
> `settings.dev.yml` is used in all other cases (development, no env var set).

## Step 5 — Install dependencies

```bash
cd telegram_adapter
uv sync
```

## Step 6 — Start the adapter

Make sure `newborn_diary` is already running (default port 8001), then:

```bash
uv run fastapi dev --port 8002
```

For production:

```bash
uv run fastapi run --port 8002
```

The adapter starts Telegram long-polling as part of its startup. You will see:

```
INFO  Starting Telegram long-polling …
INFO  Started polling
```

## Step 7 — Verify it works

1. Send a message in the diary chat, e.g. `Правая`.
2. The bot should reply within a few seconds:
   ```
   ✅ Сохранил:
   🍼 11:42 грудь (правая)
   ```
3. Send `/menu` to the bot to open the inline keyboard with quick-action buttons.
4. Send `? Сколько спал вчера?` to get an answer from the QA service. If `question_topic_id` is
   configured, plain text in that topic is also treated as a question.

## Inline keyboard actions

Send `/menu` or `/start` to display the action keyboard:

| Section | Buttons |
|---|---|
| 🍼 Кормление | 🍼 Левая, 🍼 Правая, 🍶 Смесь, 🍶 Сцеженное, 🥛 Сцедила |
| 🚼 Подгузник | 💧 Пописал, 💩 Покакал, 🚼 Подгузник |
| 😴 Сон | 😴 Заснул, 🌅 Проснулся |
| 🤸 Активность | 🛁 Купание, 🤸 На животике |
| 🤧 Симптомы | 🤧 Срыгнул чуть, 🤮 Срыгнул много, 💨 Газики |
| 💊 Прочее | 💊 Витамин Д, ❓ Спросить |

Tapping a button records the event immediately with the current timestamp.

## Free-text commands

| Input | What happens |
|---|---|
| Any plain text (from allowed author) | Parsed by LLM, saved as events, confirmed in reply |
| `? <question>` | Routes to QA service, answers the question |
| `/ask <question>` | Same as above |
| `/ask` (no question) | Bot prompts you, then your next message is the question |
| `/menu` or `/start` | Shows inline keyboard |

If your Telegram group uses forum topics, fill in `event_topic_id` with the topic ID where diary
messages should be parsed as events, and `question_topic_id` with the topic ID where the bot should
accept and answer questions. When `question_topic_id` is set, any plain text in that topic is a
question. Leave either value `null` to keep accepting that route in any topic.

## Troubleshooting

**Bot does not reply to messages**
- Check that the bot is in the chat and has the Admin / Read messages permission.
- Verify `allowed_chat_ids` matches the actual chat ID (negative number for groups).
- Check `allowed_authors` — if set, only those display names are processed.

**`allowed_authors` name does not match**
- The name compared is the Telegram **display name** (first name + last name as shown in the app), not the @username. Check the exact string in Telegram and update `settings.dev.yml`.

**Bot token rejected (401 Unauthorized)**
- The token was copied incorrectly. Go back to @BotFather, send `/mybots` → select your bot → **API Token** to view/regenerate.

**newborn_diary unreachable**
- Make sure `newborn_diary` is running and `diary_api.base_url` in settings points to the correct host/port.
- If running on separate machines, replace `localhost` with the actual IP/hostname.
