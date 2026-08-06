import torch

from src.whisper.interfaces import SpeechDetector
from src.whisper.models import SpeechDetectionResult


class SileroSpeechDetector(SpeechDetector):

    def __init__(self, **kwargs):

        self.sample_rate = kwargs.get("sample_rate", 16000)
        self.threshold = kwargs.get("threshold", 0.5)

        if self.sample_rate != 16000:
            raise ValueError(
                f"SileroSpeechDetector requires a 16000 Hz sample rate "
                f"(got {self.sample_rate})"
            )
import torch

from src.whisper.interfaces import SpeechDetector
from src.whisper.models import SpeechDetectionResult


class SileroSpeechDetector(SpeechDetector):

    def __init__(self, **kwargs):

        self.sample_rate = kwargs.get(
            "sample_rate",
            16000
        )

        self.threshold = kwargs.get(
            "threshold",
            0.5
        )

        if self.sample_rate != 16000:
            raise ValueError(
                "SileroSpeechDetector requires 16000Hz audio"
            )


        print("Loading Silero VAD model...")

        torch.set_num_threads(1)

        self.model, self.utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
            force_reload=False,
        )

        self.model.eval()

        print("Silero VAD loaded")


    def classify(self, audio_frame):

        if not isinstance(audio_frame, torch.Tensor):

            audio_frame = torch.from_numpy(
                audio_frame
            ).float()


        # Ensure mono
        if audio_frame.ndim > 1:
            audio_frame = audio_frame.squeeze()


        # Silero accepts:
        # 512, 1024, 1536 samples @ 16kHz
        #
        # Pipeline currently provides:
        # 1280 samples (80ms)
        #
        # Use nearest valid window:
        #
        # truncate to 1024 samples

        if len(audio_frame) > 1024:

            audio_frame = audio_frame[:1024]


        elif len(audio_frame) < 512:

            padded = torch.zeros(512)

            padded[:len(audio_frame)] = audio_frame

            audio_frame = padded


        with torch.no_grad():

            probability = self.model(
                audio_frame,
                self.sample_rate
            ).item()


        return SpeechDetectionResult(
            is_speech=(
                probability >= self.threshold
            ),
            speech_probability=probability,
        )
        print("Loading Silero VAD model...")

        torch.set_num_threads(1)

        self.model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
            force_reload=False,
        )

        self.model.eval()

        print("Silero VAD loaded")

    def detect(self, audio_frame):

        if not isinstance(audio_frame, torch.Tensor):
            audio_frame = torch.tensor(
                audio_frame,
                dtype=torch.float32,
            )

        with torch.no_grad():
            speech_probability = self.model(
                audio_frame,
                self.sample_rate,
            ).item()

        return SpeechDetectionResult(
            is_speech=speech_probability >= self.threshold,
            speech_probability=speech_probability,
        )
        
