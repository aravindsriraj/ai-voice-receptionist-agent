"""Audio transcoding between Twilio (8kHz mu-law) and Gemini Live (16k/24k PCM).

ADK performs NO audio conversion: it needs 16-bit PCM @ 16kHz mono in, and emits
16-bit PCM @ 24kHz mono out. Twilio Media Streams carry 8kHz mu-law (G.711).
"""
from __future__ import annotations
import audioop  # stdlib on Python 3.12; use audioop-lts on 3.13+

_WIDTH = 2      # 16-bit samples
_CHANNELS = 1   # mono


class Resampler:
    """Stateful linear resampler; keeps audioop.ratecv state across chunks."""

    def __init__(self, in_rate: int, out_rate: int) -> None:
        self._in_rate = in_rate
        self._out_rate = out_rate
        self._state = None

    def resample(self, pcm16_bytes: bytes) -> bytes:
        converted, self._state = audioop.ratecv(
            pcm16_bytes, _WIDTH, _CHANNELS, self._in_rate, self._out_rate, self._state
        )
        return converted


def ulaw8k_to_pcm16k(ulaw_bytes: bytes, resampler: Resampler) -> bytes:
    """Twilio inbound: 8kHz mu-law -> 16kHz 16-bit PCM (Gemini input)."""
    pcm_8k = audioop.ulaw2lin(ulaw_bytes, _WIDTH)
    return resampler.resample(pcm_8k)


def pcm24k_to_ulaw8k(pcm24k_bytes: bytes, resampler: Resampler) -> bytes:
    """Gemini output: 24kHz 16-bit PCM -> 8kHz mu-law (Twilio outbound)."""
    pcm_8k = resampler.resample(pcm24k_bytes)
    return audioop.lin2ulaw(pcm_8k, _WIDTH)
