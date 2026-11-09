"""Observed-cost smoke budget admission; forecasts are not billing guarantees."""
from decimal import Decimal
from openai.resources.chat.completions import AsyncCompletions


class SpendGuard:
    def __init__(self, limit):
        self.limit = Decimal(str(limit))
        if self.limit <= 0:
            raise ValueError("Spend limit must be positive")
        self.accounted = Decimal(0)
        self.observed = []
        self.requests = 0
        self.unknown_usage = False

    def reserve(self):
        # Bootstrap only until the first observation. Thereafter use the
        # most expensive of the last five observed calls plus a 50% margin.
        prediction = max(self.observed[-5:] or [Decimal("0.01")]) * Decimal("1.5")
        if self.unknown_usage or self.accounted + prediction > self.limit:
            raise RuntimeError("Smoke spend limit: next observed-cost forecast does not fit; request not sent")
        self.accounted += prediction
        self.requests += 1
        return prediction

    def settle(self, reservation, usage):
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)
        if cached is None:
            self.unknown_usage = True
            return
        actual = (Decimal(usage.prompt_tokens - cached) * Decimal("2.50") +
                  Decimal(cached) * Decimal("1.25") + Decimal(usage.completion_tokens) * 10) / 1000000
        self.accounted += actual - reservation
        self.observed.append(actual)

    def summary(self):
        return {"limit_usd": str(self.limit), "reported_cost_usd": str(sum(self.observed, Decimal(0))),
                "accounted_usd": str(self.accounted), "requests": self.requests,
                "unknown_usage": self.unknown_usage, "forecast": "max(last 5 observed calls) * 1.5; bootstrap $0.015"}

    def __enter__(self):
        original = AsyncCompletions.create
        self.original = original
        guard = self

        async def guarded(client, *args, **kwargs):
            if kwargs.get("model") != "gpt-4o" or not kwargs.get("stream"):
                raise ValueError("Spend guard supports streaming gpt-4o only")
            kwargs.pop("max_tokens", None)
            kwargs["max_completion_tokens"] = 512
            reservation = guard.reserve()
            try:
                stream = await original(client, *args, **kwargs)
            except BaseException:
                guard.unknown_usage = True
                raise

            async def watched():
                settled = False
                try:
                    async for chunk in stream:
                        if chunk.usage and not settled:
                            guard.settle(reservation, chunk.usage)
                            settled = True
                        yield chunk
                finally:
                    if not settled:
                        guard.unknown_usage = True
                    await stream.close()
            return watched()

        AsyncCompletions.create = guarded
        return self

    def __exit__(self, *args):
        AsyncCompletions.create = self.original
