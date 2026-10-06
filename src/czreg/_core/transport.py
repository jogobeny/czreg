from typing import TYPE_CHECKING, ClassVar, Final, Self, cast

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    wait_exponential_jitter,
)

if TYPE_CHECKING:
    from pyrate_limiter import Limiter

_RETRY_STATUSES: Final = frozenset({408, 429, 500, 502, 503, 504})


def _return_last_value(retry_state: RetryCallState):
    """Return the final attempt. Do not let tenacity raise `RetryError`.

    With the response available, the source client makes the correct `SourceError` from it. A
    transport failure keeps its httpx form, because `outcome.result()` raises it again.
    """
    assert retry_state.outcome is not None
    return cast("httpx.Response", retry_state.outcome.result())


def _is_retryable(response: httpx.Response):
    return response.status_code in _RETRY_STATUSES


_RETRY_CONDITION = retry_if_exception_type(httpx.TransportError) | retry_if_result(_is_retryable)


def _limiter(rates: tuple[tuple[int, int], ...]) -> "Limiter":
    try:
        from pyrate_limiter import Limiter, Rate
    except ImportError:
        msg = "rate_limit=True needs the ratelimit extra: pip install 'czreg[ratelimit]'"
        raise ImportError(msg) from None
    return Limiter([Rate(limit, seconds * 1000) for limit, seconds in rates])


class HttpClient:
    """The base of each source client: an httpx client, the retries, and the rate limit.

    A subclass sets `rates`, the limits of its source as (requests, seconds); none by default.
    `rate_limit=True` keeps to them, counting the requests of this instance. It needs the
    `ratelimit` extra.
    """

    rates: ClassVar[tuple[tuple[int, int], ...]] = ()

    def __init__(self, *, rate_limit: bool = False, timeout: float = 10.0, max_retries: int = 3):
        self.max_retries: int = max_retries
        self._limiter: Limiter | None = _limiter(self.rates) if rate_limit and self.rates else None
        self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=timeout)

    async def send(self, request: httpx.Request) -> httpx.Response:
        """Wait for the limiter, send the request, retry a transport error, 408, 429, and 5xx.

        The client does not wrap network failures. After the last retry, they go to the caller
        as httpx errors (`httpx.TimeoutException`, `httpx.ConnectError`, ...).
        """

        async def attempt_once():
            if self._limiter is not None:
                await self._limiter.try_acquire_async("czreg")
            return await self._client.send(request)

        retrying = AsyncRetrying(
            stop=stop_after_attempt(self.max_retries + 1),
            wait=wait_exponential_jitter(initial=0.5, max=8.0),
            retry=_RETRY_CONDITION,
            retry_error_callback=_return_last_value,
        )
        return await retrying(attempt_once)

    async def aclose(self):
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object):
        await self.aclose()
