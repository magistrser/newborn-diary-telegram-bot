# telegram_adapter project memory

Last revised: 2026-05-10.

## Purpose

`telegram_adapter` is an aiogram v3 Telegram bot plus small FastAPI health/metrics app. It bridges
a family Telegram chat to `newborn_diary`, forwards free text for parsing, sends quick actions,
supports event correction callbacks, asks questions, and persists failed diary API calls for retry.

## Architecture

- `domain/`: adapter-owned rules and models: pending retry actions, quick-action definitions,
  access policy, and compatible payload-field merge rules.
- `application/`: ports and retry queue orchestration. It must not import `infrastructure`.
- `infrastructure/`: aiogram handlers/keyboards/runner, httpx diary API client, SQLAlchemy models
  and repositories, FastAPI health/metrics, and composition.
- `infrastructure/composition.py`: canonical composition root. Use it to build the FastAPI app,
  diary API client, and retry queue.
- `main.py`: FastAPI app entrypoint only.

## Core behavior

- Allowed chat/author filtering gates normal text handling.
- Messages starting with `?` and `/ask` use the diary QA endpoint.
- Normal text calls `POST /api/v1/events/from-text`; failures are enqueued as `parse_text`.
- Quick-action failures are enqueued as `create_event`.
- Type-change callbacks merge only compatible common fields, currently `duration_min`.
- Retry actions survive restarts through `SqlPendingActionsRepository`.

## Guardrails

- Keep httpx, aiogram, SQLAlchemy, FastAPI, and settings wiring in infrastructure.
- Keep retry queue behavior independent of concrete HTTP and persistence adapters.
- Keep Telegram callback data within Telegram's 64-byte limit.
- Do not put generated Python artifacts under `application`, `domain`, or `infrastructure`.

## Verification

Use a cache prefix so verification does not write `__pycache__` into source packages:

- `PYTHONPYCACHEPREFIX=/tmp/telegram-adapter-pyc .venv/bin/flake8`
- `PYTHONPYCACHEPREFIX=/tmp/telegram-adapter-pyc .venv/bin/mypy .`
- `PYTHONPYCACHEPREFIX=/tmp/telegram-adapter-pyc .venv/bin/pytest -q`
