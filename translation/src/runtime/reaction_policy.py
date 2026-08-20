"""Configuration-driven selection of modulation strategies, not scheduling."""

import random


class ReactionPolicy:
    def __init__(self, strategies, policies, rng=None):
        self.strategies, self.policies = dict(strategies), dict(policies)
        self.rng = rng or random.Random()
        self._validate()

    def select(self, category="default"):
        policy = self.policies.get(category, self.policies.get("default"))
        if policy is None:
            raise ValueError("reaction_policy requires a default policy")
        mode = policy["mode"]
        if mode == "fixed":
            name = policy["strategy"]
        elif mode == "uniform":
            name = self.rng.choice(policy["choices"])
        else:
            choices = policy["choices"]
            names, weights = zip(*choices.items())
            name = self.rng.choices(names, weights=weights, k=1)[0]
        return name, dict(self.strategies[name])

    def _validate(self):
        for category, policy in self.policies.items():
            mode = policy.get("mode")
            if mode not in {"fixed", "uniform", "weighted"}:
                raise ValueError("Invalid reaction policy mode for %s: %r" % (category, mode))
            choices = [policy.get("strategy")] if mode == "fixed" else policy.get("choices", {})
            names = choices if not isinstance(choices, dict) else choices.keys()
            unknown = set(names) - set(self.strategies)
            if unknown:
                raise ValueError("Unknown reaction strategy: %s" % sorted(unknown)[0])
            if mode == "weighted":
                weights = choices.values()
                if any(weight < 0 for weight in weights) or not any(weights):
                    raise ValueError("Weighted reaction policy requires non-negative, non-zero weights")
            if mode == "uniform" and not choices:
                raise ValueError("Uniform reaction policy requires choices")
