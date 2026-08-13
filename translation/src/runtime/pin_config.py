"""GPIO topology lives in translation/configs/hardware.yaml.

This module is retained only as a compatibility import for local diagnostics.
New code should import ``get_solenoid_pin_map`` from configs.runtime_config.
"""

from configs.runtime_config import get_solenoid_pin_map


def load_pin_map():
    return get_solenoid_pin_map()


# Compatibility for older local diagnostic scripts. The value is loaded from
# hardware.yaml; it is not an implementation-owned GPIO mapping.
PIN_MAP = load_pin_map()
