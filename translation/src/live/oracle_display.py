"""Small non-blocking Oracle display boundary.

Rendering may be replaced by a Pygame process without changing Voice.  The
headless controller is the default for tests and unattended development.
"""
from __future__ import annotations

import textwrap
import time
from dataclasses import dataclass

LISTENING_TEXT = "The Oracle awaits your question. Whisper it to the water."
INITIALIZING_TEXT = "The Oracle stirs..."
WHISPER_TEXT = "The Oracle is listening to your question..."
PROCESSING_TEXT = "The Oracle is considering your question..."
RESPONSE_TITLE = "The Oracle responds"


@dataclass(frozen=True)
class DisplayConfig:
    width: int = 800
    height: int = 480
    fullscreen: bool = False
    enabled: bool = False
    minimum_response_seconds: float = 8.0
    scroll_pixels_per_second: float = 28.0
    chars_per_line: int | None = None


class OracleDisplayController:
    """Command-oriented display facade; calls are constant-time and nonblocking."""
    def __init__(self, config=DisplayConfig(), *, clock=time.monotonic):
        self.config, self.clock = config, clock
        self.view, self.response_text, self._complete_at, self._completion_sent = "idle", "", None, False

    def show_listening(self): self.view, self._complete_at = "listening", None
    def show_initializing(self): self.view, self._complete_at = "initializing", None
    def show_whisper_detected(self): self.view, self._complete_at = "whisper_detected", None
    def show_processing(self): self.view, self._complete_at = "capture_processing", None

    def layout(self, text: str) -> dict:
        chars = self.config.chars_per_line or max(24, self.config.width // 18)
        lines = textwrap.wrap(text, width=chars, replace_whitespace=False) or [""]
        available_lines = max(2, (self.config.height - 150) // 30)
        scrolling = len(lines) > available_lines
        extra_pixels = max(0, len(lines) - available_lines) * 30
        duration = self.config.minimum_response_seconds + (extra_pixels / self.config.scroll_pixels_per_second if scrolling else 0)
        return {"lines": lines, "scrolling": scrolling, "duration": duration}

    def show_response(self, text: str):
        self.view, self.response_text, self._completion_sent = "response", text, False
        self._complete_at = self.clock() + self.layout(text)["duration"]

    def poll(self) -> bool:
        if self._complete_at is not None and not self._completion_sent and self.clock() >= self._complete_at:
            self._completion_sent = True
            return True
        return False

    def close(self): pass


class PygameOracleDisplayController(OracleDisplayController):
    """SDL/Pygame 2 renderer; imports pygame only when an actual screen is used."""
    def __init__(self, config=DisplayConfig(), **kwargs):
        super().__init__(config, **kwargs)
        try:
            import pygame
        except ImportError as exc:
            raise RuntimeError("Oracle display requires pygame>=2; use --oracle-headless for development") from exc
        self.pygame = pygame
        pygame.init()
        flags = pygame.FULLSCREEN if config.fullscreen else 0
        self.surface = pygame.display.set_mode((config.width, config.height), flags)
        self.font = pygame.font.Font(None, max(22, config.height // 18))
        self.title_font = pygame.font.Font(None, max(28, config.height // 12))
        self._draw_static(LISTENING_TEXT)

    def _draw_static(self, body, title=None, offset=0):
        pygame = self.pygame; self.surface.fill((8, 18, 28))
        y = max(24, self.config.height // 12) - offset
        if title:
            self.surface.blit(self.title_font.render(title, True, (198, 221, 227)), (self.config.width // 12, y)); y += self.title_font.get_height() * 2
        for line in self.layout(body)["lines"]:
            self.surface.blit(self.font.render(line, True, (236, 241, 238)), (self.config.width // 12, y)); y += self.font.get_height() + 8
        pygame.display.flip()

    def show_listening(self): super().show_listening(); self._draw_static(LISTENING_TEXT)
    def show_initializing(self): super().show_initializing(); self._draw_static(INITIALIZING_TEXT)
    def show_whisper_detected(self): super().show_whisper_detected(); self._draw_static(WHISPER_TEXT)
    def show_processing(self): super().show_processing(); self._draw_static(PROCESSING_TEXT)
    def show_response(self, text): super().show_response(text); self._response_started = self.clock(); self._draw_static(text, RESPONSE_TITLE)

    def poll(self):
        self.pygame.event.pump()
        if self.view == "response" and self.layout(self.response_text)["scrolling"]:
            offset = int((self.clock() - self._response_started) * self.config.scroll_pixels_per_second)
            self._draw_static(self.response_text, RESPONSE_TITLE, offset)
        return super().poll()

    def close(self): self.pygame.quit()
