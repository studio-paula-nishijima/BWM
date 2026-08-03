"""
Detector interfaces.

Contains only abstract detector contracts.

Concrete implementations live in:

    whisper.detectors
"""

from abc import ABC, abstractmethod


class WhisperDetector(ABC):
    """
    Interface for whisper classifiers.
    """

    @abstractmethod
    def classify(self, frame):
        pass



class SpeechDetector(ABC):
    """
    Interface for speech presence classifiers.
    """

    @abstractmethod
    def classify(self, frame):
        pass
