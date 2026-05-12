from application.dto import RetryResult


def test_retry_result_stores_counts() -> None:
    result = RetryResult(succeeded=2, failed=1)

    assert result.succeeded == 2
    assert result.failed == 1
