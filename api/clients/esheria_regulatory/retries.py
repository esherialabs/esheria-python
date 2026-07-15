from __future__ import annotations

import time


RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


def retry_delay_seconds(attempt_index: int) -> float:
    return min(2.0, 0.2 * (2 ** max(0, attempt_index)))


def sleep_before_retry(attempt_index: int) -> None:
    time.sleep(retry_delay_seconds(attempt_index))
