
import functools
import requests
import time 
import random 
import logging
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------
RETRY_MAX_ATTEMPTS = 5       # total attempts (1 original + 4 retries)
RETRY_BASE_DELAY   = 1.0     # seconds — delay before the 1st retry
RETRY_MAX_DELAY    = 60.0    # seconds — cap on any single sleep
RETRY_MULTIPLIER   = 2.0     # exponential growth factor
RETRY_JITTER       = 0.3     # fraction of delay added as random jitter


# HTTP status codes that should NOT be retried (auth/client errors)
_NO_RETRY_STATUSES = {400, 401, 403, 404, 405, 409, 422}


def _should_retry(exc_or_response) -> bool:
    """Return True when the error / status code is worth retrying."""
    if isinstance(exc_or_response, Exception):
        # Only retry network/IO errors, not programming bugs
        return isinstance(exc_or_response, (requests.exceptions.RequestException, OSError))
    # treat HTTP 429, 5xx as transient; never retry auth failures
    if hasattr(exc_or_response, "status_code"):
        if exc_or_response.status_code in _NO_RETRY_STATUSES:
            return False
        return exc_or_response.status_code in {429, 500, 502, 503, 504}
    return False


def with_exponential_retry(
    max_attempts: int = RETRY_MAX_ATTEMPTS,
    base_delay: float = RETRY_BASE_DELAY,
    max_delay: float = RETRY_MAX_DELAY,
    multiplier: float = RETRY_MULTIPLIER,
    jitter: float = RETRY_JITTER,
    reraise_as=None,
    label: str = "request",
):
    """
    Decorator that wraps any method with exponential-backoff retry logic.

    The wrapped method is retried when it either:
      • raises a requests.exceptions.RequestException (or any Exception), OR
      • returns a response object with a transient HTTP status (429 / 5xx).

    
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc = None

            for attempt in range(1, max_attempts + 1):
                try:
                    result = func(*args, **kwargs)

                    # If the call returned a response, check the status.
                    if hasattr(result, "status_code") and _should_retry(result):
                        logger.warning(
                            "[%s] attempt %d/%d — HTTP %d, retrying in %.1fs …",
                            label, attempt, max_attempts, result.status_code, delay,
                        )
                        # On last attempt just return the bad response so the
                        # caller can inspect it (same behaviour as before).
                        if attempt == max_attempts:
                            return result
                    else:
                        return result  # success

                except Exception as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        logger.error(
                            "[%s] all %d attempts failed. Last error: %s",
                            label, max_attempts, exc,
                        )
                        if reraise_as:
                            raise reraise_as(str(exc)) from exc
                        raise

                    logger.warning(
                        "[%s] attempt %d/%d failed (%s: %s), retrying in %.1fs …",
                        label, attempt, max_attempts, type(exc).__name__, exc, delay,
                    )

                # Exponential back-off with jitter
                sleep_time = min(delay * (1 + jitter * random.random()), max_delay)
                time.sleep(sleep_time)
                delay = min(delay * multiplier, max_delay)

            # Should never reach here, but just in case:
            if last_exc:
                raise last_exc

        return wrapper
    return decorator

