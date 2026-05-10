from dataclasses import dataclass


@dataclass(frozen=True)
class RetryResult:
    succeeded: int
    failed: int
