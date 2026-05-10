from prometheus_client import CollectorRegistry, Counter, Histogram


prometheus_registry = CollectorRegistry()


DURATION_SECONDS = Histogram(
    'telegram_adapter_duration_seconds',
    'Time spent processing operation in target\n'
    '* target: component/service being measured (e.g., postgres, redis, http_client)\n'
    '* operation: specific action within target (e.g., select, fetch, save)',
    ['target', 'operation'],
    registry=prometheus_registry,
)


ERRORS = Counter(
    'telegram_adapter_errors_total',
    'Total number of errors occurred during operation\n'
    '* target: affected component/service (e.g., postgres, s3, api)\n'
    '* operation: failed action (e.g., query, delete, call)',
    ['target', 'operation'],
    registry=prometheus_registry,
)
