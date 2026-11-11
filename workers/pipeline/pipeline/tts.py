import logging
import os
import wave
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("narra.tts")

DEFAULT_MODEL = "/models/kokoro-v1.0.onnx"
DEFAULT_VOICES = "/models/voices-v1.0.bin"


LANG_BY_PREFIX = {"p": "pt-br", "a": "en-us", "b": "en-gb"}


def kokoro_lang(voice: str) -> str:
    """Kokoro voice ids start with the accent letter: p (pt-BR), a (en-US), b (en-GB)."""
    return LANG_BY_PREFIX.get(voice[:1], "pt-br")


class KokoroVoice:
    """Local Kokoro TTS (ONNX). Phonemization relies on espeak-ng."""

    def __init__(self, model_path: str, voices_path: str):
        from kokoro_onnx import Kokoro

        self.kokoro = Kokoro(model_path, voices_path)

    def synthesize(self, text: str, destination: Path, voice: str = "pf_dora", speed: float = 1.0) -> float:
        samples, sample_rate = self.kokoro.create(text, voice=voice, speed=speed, lang=kokoro_lang(voice))
        pcm = (samples.clip(-1, 1) * 32767).astype("<i2").tobytes()
        with wave.open(str(destination), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm)
        return len(samples) / sample_rate


@lru_cache(maxsize=1)
def load_voice() -> KokoroVoice | None:
    model = os.environ.get("KOKORO_MODEL_PATH", DEFAULT_MODEL)
    voices = os.environ.get("KOKORO_VOICES_PATH", DEFAULT_VOICES)
    if not (Path(model).is_file() and Path(voices).is_file()):
        logger.warning("Kokoro model files not found (%s, %s); rendering without narration", model, voices)
        return None
    try:
        return KokoroVoice(model, voices)
    except Exception as exc:  # noqa: BLE001 - optional dependency
        logger.warning("Kokoro unavailable: %s", exc)
        return None
