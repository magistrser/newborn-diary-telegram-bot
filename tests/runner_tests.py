from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

from infrastructure.telegram import runner


@pytest.fixture(autouse=True)
def reset_runner_state() -> Generator[None, None, None]:
    runner._state = runner._RunnerState()
    yield
    runner._state = runner._RunnerState()


async def test_polling_supervisor_restarts_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleep_calls: list[float] = []

    async def fake_run_polling_once(_engine: object, _session_factory: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError('telegram down')
        runner._state.stopping = True

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(runner, '_run_polling_once', fake_run_polling_once)
    monkeypatch.setattr(runner.asyncio, 'sleep', fake_sleep)

    await runner._polling_supervisor(MagicMock(), MagicMock(), restart_delay_sec=0.25)

    assert calls == 2
    assert sleep_calls == [0.25]


async def test_polling_supervisor_restarts_after_unexpected_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleep_calls: list[float] = []

    async def fake_run_polling_once(_engine: object, _session_factory: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            runner._state.stopping = True

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(runner, '_run_polling_once', fake_run_polling_once)
    monkeypatch.setattr(runner.asyncio, 'sleep', fake_sleep)

    await runner._polling_supervisor(MagicMock(), MagicMock(), restart_delay_sec=0.25)

    assert calls == 2
    assert sleep_calls == [0.25]


async def test_polling_supervisor_does_not_restart_during_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleep_calls: list[float] = []

    async def fake_run_polling_once(_engine: object, _session_factory: object) -> None:
        nonlocal calls
        calls += 1
        runner._state.stopping = True
        raise RuntimeError('closed by shutdown')

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(runner, '_run_polling_once', fake_run_polling_once)
    monkeypatch.setattr(runner.asyncio, 'sleep', fake_sleep)

    await runner._polling_supervisor(MagicMock(), MagicMock(), restart_delay_sec=0.25)

    assert calls == 1
    assert sleep_calls == []
