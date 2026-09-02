"""Validation and topology resolution for configured Voice reactions."""
from copy import deepcopy


def prepare_voice_reactions(strategies, policies, policy_name, targets, *, additional_policy_names=()):
    """Validate Voice-only reactions, never base modulation strategies."""
    strategies, policies, targets = deepcopy(strategies), deepcopy(policies), list(targets or ())
    policy = policies.get(policy_name)
    if policy is None:
        raise ValueError("voice_interaction.reaction_policy references missing policy: %s" % policy_name)
    selected = (policy_name, *additional_policy_names)
    names = set()
    for selected_name in selected:
        selected_policy = policies.get(selected_name)
        if selected_policy is None:
            raise ValueError("voice_interaction references missing policy: %s" % selected_name)
        names.update(_policy_names(selected_policy, selected_name))
    for name in names:
        if name not in strategies:
            raise ValueError("%s references missing reaction: %s" % (policy_name, name))
        strategies[name] = _prepare_reaction(name, strategies[name], targets)
    return strategies, policies


def _policy_names(policy, path):
    mode = policy.get("mode")
    if mode == "fixed":
        return [policy.get("strategy")]
    if mode == "uniform":
        return list(policy.get("choices", ()))
    if mode == "weighted":
        return list(policy.get("choices", {}).keys())
    raise ValueError("%s has invalid reaction policy mode: %r" % (path, mode))


def _prepare_reaction(name, config, topology):
    path, config = "voice reaction %s" % name, deepcopy(config)
    kind = config.get("type")
    if kind == "override_sequence":
        _non_negative(config.get("initial_quiet_gap_seconds", 0), path + ".initial_quiet_gap_seconds")
        phases = config.get("phases")
        if not isinstance(phases, list) or not phases:
            raise ValueError(path + ".phases must be a non-empty list")
        for index, phase in enumerate(phases):
            phase_path = "%s.phases[%d]" % (path, index)
            if not isinstance(phase, dict) or phase.get("type") not in {"simultaneous", "sequence", "wait"}:
                raise ValueError(phase_path + " has unknown phase type")
            if phase["type"] == "wait":
                _non_negative(phase.get("duration_seconds"), phase_path + ".duration_seconds")
            else:
                phase["targets"] = _resolve_targets(phase.get("targets"), topology, phase_path + ".targets")
                if phase["type"] == "sequence":
                    _non_negative(phase.get("spacing_seconds"), phase_path + ".spacing_seconds")
        return config
    if kind == "repeat_transform":
        _non_negative(config.get("duration_seconds"), path + ".duration_seconds")
        count = config.get("repeat_count")
        if not isinstance(count, int) or count < 1:
            raise ValueError(path + ".repeat_count must be an integer >= 1")
        _non_negative(config.get("tap_spacing_seconds"), path + ".tap_spacing_seconds")
        return config
    raise ValueError(path + " has unknown reaction type: %r" % kind)


def _resolve_targets(value, topology, path):
    if value == "all":
        if not topology:
            raise ValueError(path + " uses 'all' but no actuator topology was supplied")
        return list(topology)
    if not isinstance(value, list) or not value:
        raise ValueError(path + " must be 'all' or a non-empty target list")
    unknown = set(value).difference(topology)
    if unknown:
        raise ValueError(path + " includes unknown target: %s" % sorted(unknown)[0])
    return list(value)


def _non_negative(value, path):
    if not isinstance(value, (int, float)) or value < 0:
        raise ValueError(path + " must be a number >= 0")
