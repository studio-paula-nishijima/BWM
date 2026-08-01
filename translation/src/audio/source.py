from dataclasses import dataclass
from abc import ABC, abstractmethod
import numpy as np


@dataclass
class AudioFrame:
    samples: np.ndarray
    timestamp: float
    frame_number: int


class AudioSource(ABC):

    @abstractmethod
    def open(self):
        pass

    @abstractmethod
    def read_frame(self):
        pass

    @abstractmethod
    def close(self):
        pass
