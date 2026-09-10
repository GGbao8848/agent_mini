"""Embedding client for semantic memory retrieval (ported from aimemory).

Talks to any OpenAI-compatible ``/v1/embeddings`` endpoint. Two properties
matter more than the HTTP call itself:

- **Never a hard dependency.** Any failure returns ``None`` and the caller
  falls back to keyword retrieval — a flaky embedding service must not break
  memory, only reduce its recall quality.
- **Half-open circuit breaker.** After ``_BREAK_THRESHOLD`` consecutive
  failures the breaker opens for ``_RETRY_SECONDS``, during which calls return
  immediately; one probe every retry window checks for recovery. aimemory's
  lesson: an early "fail once, degrade until restart" design meant a momentary
  blip killed semantic search for the whole process.
"""

from __future__ import annotations

import asyncio
import time

import httpx

_BREAK_THRESHOLD = 3
_RETRY_SECONDS = 60.0
_MAX_CONCURRENCY = 4

Vector = list[float]


class EmbeddingClient:
    """Bounded, self-healing embeddings client. Returns ``None`` on failure."""

    def __init__(
        self,
        *,
        base_url: str | None,
        model: str | None,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        enabled: bool = True,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._model = model or ""
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._enabled = enabled and bool(self._base_url and self._model)
        self._failures = 0
        self._open_until = 0.0
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    @property
    def enabled(self) -> bool:
        """True when a usable endpoint is configured."""
        return self._enabled

    def _blocked(self) -> bool:
        if self._open_until == 0.0:
            return False
        if time.monotonic() >= self._open_until:
            # Retry window elapsed: let one call probe and reset the counter.
            self._open_until = 0.0
            self._failures = 0
            return False
        return True

    def _record_failure(self) -> None:
        self._failures += 1
        if self._failures >= _BREAK_THRESHOLD:
            self._open_until = time.monotonic() + _RETRY_SECONDS

    def _record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    async def embed(self, text: str) -> Vector | None:
        """Return the embedding for ``text``, or ``None`` on any failure."""
        if not self._enabled or not text.strip() or self._blocked():
            return None
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base_url}/embeddings",
                        headers=headers,
                        json={"model": self._model, "input": text},
                    )
                response.raise_for_status()
                vector = response.json()["data"][0]["embedding"]
            except Exception:  # noqa: BLE001 - any failure degrades to keywords
                self._record_failure()
                return None
        if not isinstance(vector, list) or not vector:
            self._record_failure()
            return None
        self._record_success()
        return [float(value) for value in vector]
