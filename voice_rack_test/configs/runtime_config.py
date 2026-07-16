from pathlib import Path
import yaml
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_runtime_config():

    config_path = (
        PROJECT_ROOT /
        "configs" /
        "runtime.yaml"
    )

    with open(config_path) as f:

        return yaml.safe_load(f)


RUNTIME_CONFIG = load_runtime_config()


# ---------------------------------------------------
# Centralized src path injection
# ---------------------------------------------------

SRC_PATH = (
    PROJECT_ROOT /
    RUNTIME_CONFIG["project"]["src_path"]
)

if str(SRC_PATH) not in sys.path:

    sys.path.append(str(SRC_PATH))
