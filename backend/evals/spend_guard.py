"""Observed-cost smoke budget admission; forecasts are not billing guarantees."""
from decimal import Decimal
from openai.resources.chat.completions import AsyncCompletions


class SpendGuard:
    def __init__(self, limit, *, strict_admission=False, bound_unknown=False):
        self.limit = Decimal(str(limit))
        if self.limit <= 0:
            raise ValueError("Spend limit must be positive")
        self.accounted = Decimal(0)
        self.observed = []
        self.requests = 0
        self.unknown_usage = False
        self.stopped = False
        self.stop_reason = None
        self.strict_admission = strict_admission
        self.bound_unknown = bound_unknown
        self.unknown_requests = 0

    def account_unknown(self, reservation):
        self.unknown_usage = True
        self.unknown_requests += 1
        if self.bound_unknown:
            # GPT-4o: <=128K context, output cap 512. Entire context charged
            # uncached plus capped output is a deliberately loose *bound*,
            # never a reported/estimated actual charge.
            self.accounted += Decimal("0.32512") - reservation

    def stop(self, reason):
        self.stopped = True
        self.stop_reason = reason
        raise RuntimeError(reason)

    def reserve(self):
        # Bootstrap only until the first observation. Thereafter use the
        # most expensive of the last five observed calls plus a 50% margin.
        prediction = max(self.observed[-5:] or [Decimal("0.01")]) * Decimal("1.5")
        if self.stopped or (self.unknown_usage and not self.bound_unknown) or self.accounted + prediction > self.limit:
            self.stop("Spend limit: next observed-cost forecast does not fit or usage unknown; request not sent")
        self.accounted += prediction
        self.requests += 1
        return prediction

    def settle(self, reservation, usage):
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)
        if cached is None:
            self.account_unknown(reservation)
            return
        actual = (Decimal(usage.prompt_tokens - cached) * Decimal("2.50") +
                  Decimal(cached) * Decimal("1.25") + Decimal(usage.completion_tokens) * 10) / 1000000
        self.accounted += actual - reservation
        self.observed.append(actual)

    def summary(self):
        return {"limit_usd": str(self.limit), "reported_cost_usd": str(sum(self.observed, Decimal(0))),
                "accounted_usd": str(self.accounted), "requests": self.requests,
                "stopped": self.stopped, "stop_reason": self.stop_reason,
                "unreported_requests": self.unknown_requests,
                "unreported_cost_usd": None if self.unknown_requests else "0",
                "unreported_exposure_bound_usd": str(Decimal("0.32512") * self.unknown_requests),
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
            if guard.strict_admission:
                # Keep the observed-cost reservation. Additionally refuse a
                # near-cap request if a cold prompt + capped output could not
                # fit. Serialized-request tokens plus framing margin provide
                # conservative headroom without relying on a future cache hit.
                import json
                import tiktoken
                count = len(tiktoken.encoding_for_model("gpt-4o").encode(json.dumps(
                    {k: kwargs[k] for k in ("messages", "tools") if k in kwargs}, default=str)))
                upper_input = int(count * 1.15) + 512
                upper_cost = (Decimal(upper_input) * Decimal("2.50") + Decimal(512) * 10) / 1000000
                admission = max(upper_cost, Decimal("0.32512")) if guard.bound_unknown else upper_cost
                if guard.accounted + admission > guard.limit:
                    guard.stop("Spend limit: cold-request safety admission does not fit; request not sent")
            reservation = guard.reserve()
            try:
                stream = await original(client, *args, **kwargs)
            except BaseException:
                guard.account_unknown(reservation)
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
                        guard.account_unknown(reservation)
                    await stream.close()
            return watched()

        AsyncCompletions.create = guarded
        return self

    def __exit__(self, *args):
        AsyncCompletions.create = self.original
