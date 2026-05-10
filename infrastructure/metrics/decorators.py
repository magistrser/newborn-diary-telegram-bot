from functools import wraps
from inspect import iscoroutinefunction
from time import perf_counter
from typing import Any, Callable

from .main import DURATION_SECONDS, ERRORS


def _get_labels(func: Callable, target: str | Callable | None, operation: str | None) -> tuple[str, str]:
    if isinstance(target, str):
        return target, operation or func.__qualname__.split('.')[-1]
    else:
        names = func.__qualname__.split('.')

        if len(names) > 1:
            return names[-2], operation or names[-1]
        else:
            return 'global', operation or names[-1]


def duration_tracking(target: str | Callable | None = None, operation: str | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        target_name, operation_name = _get_labels(func, target, operation)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                duration = perf_counter() - start
                DURATION_SECONDS.labels(target=target_name, operation=operation_name).observe(duration)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration = perf_counter() - start
                DURATION_SECONDS.labels(target=target_name, operation=operation_name).observe(duration)

        return async_wrapper if iscoroutinefunction(func) else sync_wrapper

    return decorator(target) if callable(target) else decorator


def error_tracking(target: str | Callable | None = None, operation: str | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        target_name, operation_name = _get_labels(func, target, operation)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as error:
                ERRORS.labels(target=target_name, operation=operation_name).inc()
                raise error

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as error:
                ERRORS.labels(target=target_name, operation=operation_name).inc()
                raise error

        return async_wrapper if iscoroutinefunction(func) else sync_wrapper

    return decorator(target) if callable(target) else decorator


def metrics(target: str | Callable | None = None, operation: str | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        target_name, operation_name = _get_labels(func, target, operation)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = perf_counter()
            try:
                return await func(*args, **kwargs)
            except Exception as error:
                ERRORS.labels(target=target_name, operation=operation_name).inc()
                raise error
            finally:
                duration = perf_counter() - start
                DURATION_SECONDS.labels(target=target_name, operation=operation_name).observe(duration)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = perf_counter()
            try:
                return func(*args, **kwargs)
            except Exception as error:
                ERRORS.labels(target=target_name, operation=operation_name).inc()
                raise error
            finally:
                duration = perf_counter() - start
                DURATION_SECONDS.labels(target=target_name, operation=operation_name).observe(duration)

        return async_wrapper if iscoroutinefunction(func) else sync_wrapper

    return decorator(target) if callable(target) else decorator
