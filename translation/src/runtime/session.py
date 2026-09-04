"""Persistent activation runtime with wall-clock bounded playback sessions."""

import threading

from runtime.modulation import RuntimeModulationEngine
from runtime.playback import PlaybackEngine
from runtime.reaction_policy import ReactionPolicy
from runtime.safety import RuntimeSafety
from runtime.voice_reactions import prepare_voice_reactions


class PlaybackSessionRuntime:
    """Keep an installation runtime alive while creating clean sessions on activation."""

    def __init__(self, events_factory, clock, dispatcher, session_timeout, initially_active=False,
                 event_logger=None, safety_config=None, reaction_policy_config=None, rng=None,
                 whisper_interaction_config=None, reaction_targets=None, lighting_controller=None,
                 activation_publisher=None):
        self._events_factory, self._clock, self._dispatcher = events_factory, clock, dispatcher
        self._session_timeout, self._event_logger = float(session_timeout), event_logger
        self._safety = RuntimeSafety(clock, dispatcher, safety_config)
        self._whisper_interaction = dict(whisper_interaction_config or {})
        self._lighting = lighting_controller
        if reaction_policy_config is not None and self._whisper_interaction.get("enabled", False):
            selection_policy_names = tuple(
                band["reaction_policy"]
                for band in self._whisper_interaction.get("silero_selection_bands", ())
                if "reaction_policy" in band
            )
            strategies, policies = prepare_voice_reactions(
                reaction_policy_config.get("strategies", {}), reaction_policy_config.get("policies", {}),
                self._whisper_interaction.get("reaction_policy", "voice_default"), reaction_targets,
                additional_policy_names=selection_policy_names)
            reaction_policy_config = {"strategies": strategies, "policies": policies}
        self._reaction_policy = None if reaction_policy_config is None else ReactionPolicy(
            reaction_policy_config.get("strategies", {}), reaction_policy_config.get("policies", {}), rng)
        self._whisper_state = None
        self._external_reaction_busy = False
        self._changed = threading.Condition()
        self._active = False
        self._activation_publisher = activation_publisher
        self._engine = self._modulation = self._started_at = None
        if initially_active:
            # Startup is locally authoritative.  Its optional later UART
            # notification is synchronization, never startup authorization.
            self.activate(publish=False)

    @property
    def is_active(self):
        with self._changed:
            return self._active

    @property
    def engine(self): return self._engine

    @property
    def modulation(self): return self._modulation

    @property
    def safety(self): return self._safety

    @property
    def whisper_state(self):
        with self._changed:
            return self._whisper_state

    @property
    def external_reaction_busy(self):
        with self._changed:
            return self._external_reaction_busy

    def set_activation_publisher(self, publisher):
        """Attach the single outbound state-transition publication seam."""
        with self._changed:
            self._activation_publisher = publisher

    def publish_current_activation(self):
        """Best-effort startup synchronization after UART becomes available."""
        with self._changed:
            self._publish_activation("active" if self._active else "inactive")

    def activate(self, *, publish=True):
        with self._changed:
            if self._active:
                return False
            begin_session = getattr(self._dispatcher, "begin_session", None)
            if begin_session is not None:
                begin_session()
            modulation = RuntimeModulationEngine(self._clock, self._safety)
            engine = PlaybackEngine(self._events_factory(), self._clock,
                                    due_event_handler=modulation.process,
                                    event_logger=self._event_logger)
            modulation.bind_playback_control(engine)
            engine.start()
            self._engine, self._modulation = engine, modulation
            self._started_at, self._active = self._clock.now(), True
            if self._lighting:
                self._lighting.activate()
            print("[Session] ACTIVE: fresh playback session started")
            if publish:
                self._publish_activation("active")
            self._changed.notify_all()
            return True

    def deactivate(self, *, publish=True):
        """Explicit cancellation, not a logical-score pause."""
        with self._changed:
            if not self._active:
                return False
            self._finish_session("cancelled", publish=publish)
            self._changed.notify_all()
            return True

    cancel = deactivate

    def toggle(self):
        return self.deactivate() if self.is_active else self.activate()

    def trigger(self, name, **config):
        with self._changed:
            if not self._active:
                raise RuntimeError("Cannot trigger modulation while idle")
            return self._modulation.trigger(name, **config)

    def trigger_reaction(self, category="default"):
        with self._changed:
            if not self._active:
                raise RuntimeError("Cannot trigger reaction while idle")
            if self._reaction_policy is None:
                raise RuntimeError("No reaction policy configured")
            name, config = self._reaction_policy.select(category)
            # Definitions may use an artistic name while mapping to a reusable
            # Stage 4 modulation strategy.
            return self._modulation.trigger(config.pop("type", name), **config)

    def observe_whisper_state(self, state):
        """Track one semantic Voice transition and admit at most one reaction."""
        with self._changed:
            previous, self._whisper_state = self._whisper_state, state
            print(f"[WhisperLifecycle] {previous!r} -> {state!r}")
            if not self._whisper_interaction.get("enabled", False):
                return "observed_disabled"
            if previous == state:
                return "observed_no_transition"
            if state != self._whisper_interaction.get("trigger_state"):
                return "observed"
            if not self._active:
                print("[WhisperInteraction] trigger ignored: Translation session inactive")
                return "ignored_inactive"
            self._refresh_external_reaction()
            if self._external_reaction_busy:
                print("[WhisperInteraction] trigger ignored: external reaction busy")
                return "ignored_busy"
            if self._reaction_policy is None:
                return "ignored_unconfigured"
            category = self._whisper_interaction.get("reaction_policy", "voice_default")
            name, config = self._reaction_policy.select(category)
            seed = dict(config.pop("event", {"type": "solenoid", "duration": .15, "playback_time": 0}))
            if not seed.get("type"):
                raise ValueError("Voice reaction requires an event type")
            executable = config.pop("type", name)
            self._modulation.trigger_external(executable, seed, **config)
            self._external_reaction_busy = self._modulation.external_busy
            print(f"[WhisperInteraction] trigger matched; selected reaction: {name}")
            return "triggered"

    def observe_whisper_interaction(self, payload):
        """Admit a real Voice occurrence; selection remains Translation-owned."""
        source = payload.get("source")
        value = payload.get("silero_selection_value")
        with self._changed:
            if not self._active:
                return "ignored_inactive"
            if self._lighting:
                self._lighting.trigger_interaction()
            self._refresh_external_reaction()
            if self._external_reaction_busy:
                return "ignored_busy"
            if self._reaction_policy is None:
                return "ignored_unconfigured"
            category = self._whisper_interaction.get("reaction_policy", "voice_default")
            if source == "detector":
                category = self._silero_category(float(value))
            name, config = self._reaction_policy.select(category)
            seed = dict(config.pop("event", {"type": "solenoid", "duration": .15, "playback_time": 0}))
            self._modulation.trigger_external(config.pop("type", name), seed, **config)
            self._external_reaction_busy = self._modulation.external_busy
            return "triggered"

    def _silero_category(self, value):
        bands = self._whisper_interaction.get("silero_selection_bands", [])
        for band in bands:
            if value < float(band["upper_exclusive"]):
                return band["reaction_policy"]
        if not bands:
            return self._whisper_interaction.get("reaction_policy", "voice_default")
        return bands[-1]["reaction_policy"]

    def step(self):
        """Advance both clocks' work without allowing logical pause to affect timeout."""
        with self._changed:
            if not self._active:
                return 0
            if self._clock.now() - self._started_at >= self._session_timeout:
                self._finish_session("timeout")
                self._changed.notify_all()
                return 0
            dispatched = self._engine.step()
            dispatched += self._modulation.step()
            if self._lighting:
                self._lighting.step()
            self._refresh_external_reaction()
            backend_idle = getattr(self._dispatcher, "is_idle", lambda: True)
            if self._engine.is_complete and self._modulation.pending_count == 0 and backend_idle():
                self._finish_session("complete")
                self._changed.notify_all()
            return dispatched

    def wait_until_active(self):
        with self._changed:
            while not self._active:
                self._changed.wait()

    def wait_for_change(self, timeout):
        with self._changed:
            self._changed.wait(timeout)

    def _finish_session(self, reason, *, publish=True):
        """Single teardown path: close admission, clear session work, quiesce, idle."""
        print(f"[Session] TEARDOWN: {reason}; closing session admission")
        self._active = False
        self._external_reaction_busy = False
        self._modulation.cancel()
        self._engine.stop()
        if self._lighting:
            self._lighting.deactivate_async()
            self._lighting.step()
        quiesce = getattr(self._dispatcher, "quiesce", None)
        if quiesce is not None:
            quiesce()
        print("[Session] IDLE: session state cleared; hardware quiescent")
        if publish:
            self._publish_activation("inactive")

    def _publish_activation(self, state):
        if self._activation_publisher is not None:
            self._activation_publisher.publish(state)

    def _refresh_external_reaction(self):
        if self._external_reaction_busy and not self._modulation.external_busy:
            self._external_reaction_busy = False
            print("[WhisperInteraction] external reaction complete; busy cleared")
