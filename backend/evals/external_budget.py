"""Full per-request exposure reservation; independent of frozen runtime/guards."""
from decimal import Decimal
from .spend_guard import SpendGuard


class FinalSpendGuard(SpendGuard):
    def __init__(self, limit, config):
        super().__init__(limit, bound_unknown=True)
        self.config = config
        self.exposure_bound_valid = True
        p = config["prices_per_million_usd"]
        self.ceiling = (Decimal(config["max_input_tokens"]) * Decimal(str(p["input"])) +
                        Decimal(config["max_completion_tokens"]) * Decimal(str(p["output"]))) / 1_000_000
        if (config["model"], config["max_input_tokens"], config["max_completion_tokens"], p) != ("gpt-4o", 128000, 512, {"input": 2.5, "cached_input": 1.25, "output": 10}):
            raise ValueError("Budget assumptions do not match the pinned GPT-4o guard")

    def reserve(self):
        if self.stopped or self.accounted + self.ceiling > self.limit:
            self.stop("Full input/output exposure does not fit; request not sent")
        self.accounted += self.ceiling
        self.requests += 1
        return self.ceiling

    def account_unknown(self, reservation):
        self.unknown_usage = True
        self.unknown_requests += 1
        # The full ceiling is already held; never release it on cancellation.

    def settle(self, reservation, usage):
        prompt, output = getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)
        if not (type(prompt) is int and type(output) is int and 0 <= prompt <= self.config["max_input_tokens"]
                and 0 <= output <= self.config["max_completion_tokens"] and
                (cached is None or (type(cached) is int and 0 <= cached <= prompt))):
            self.account_unknown(reservation)
            self.exposure_bound_valid = False
            self.stopped = True
            self.stop_reason = "Provider usage violated configured limits; no further request; bound no longer certified"
            return
        super().settle(reservation, usage)

    def summary(self):
        result = super().summary()
        result.update(forecast="Not used for admission; full per-request ceiling reserved before sending",
                      per_request_reserved_usd=str(self.ceiling),
                      exposure_bound_valid=self.exposure_bound_valid,
                      assumptions="Provider enforces <=128000 input, <=512 output, dated GPT-4o rates, no extra model/tool fees, each request guarded, no retries")
        return result
