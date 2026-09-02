"""Small semantic MQTT topic hierarchy; topics never reveal transport or hardware."""

INSTALLATION_ACTIVATION = "installation/activation"
VOICE_STATE = "voice/state"
VOICE_INTERACTION = "voice/interaction"


class TopicNamespace:
    def __init__(self, base: str = "bwm"):
        base = base.strip("/")
        if not base:
            raise ValueError("MQTT topic base must not be empty")
        self.base = base

    def topic(self, suffix: str) -> str:
        suffix = suffix.strip("/")
        if not suffix:
            raise ValueError("MQTT topic suffix must not be empty")
        return f"{self.base}/{suffix}"

    @property
    def installation_activation(self) -> str:
        return self.topic(INSTALLATION_ACTIVATION)

    @property
    def voice_state(self) -> str:
        return self.topic(VOICE_STATE)

    @property
    def voice_interaction(self) -> str:
        return self.topic(VOICE_INTERACTION)

    def availability(self, origin: str) -> str:
        if not origin.strip():
            raise ValueError("Origin must not be empty")
        return self.topic(f"system/status/{origin}")
