import audioop
from app.audio import Resampler, ulaw8k_to_pcm16k, pcm24k_to_ulaw8k


def test_resampler_changes_rate_and_length():
    # 8kHz mono 16-bit, 100ms of silence = 800 samples * 2 bytes = 1600 bytes
    pcm_8k = b"\x00\x00" * 800
    r = Resampler(8000, 16000)
    out = r.resample(pcm_8k)
    # upsampling 8k->16k roughly doubles sample count
    assert 3000 <= len(out) <= 3400


def test_ulaw_inbound_roundtrips_to_16k_pcm():
    # build 20ms of ulaw silence (160 bytes) and confirm it decodes to 16k pcm bytes
    ulaw = audioop.lin2ulaw(b"\x00\x00" * 160, 2)  # 160 samples @ 8k
    r = Resampler(8000, 16000)
    pcm16k = ulaw8k_to_pcm16k(ulaw, r)
    assert isinstance(pcm16k, bytes) and len(pcm16k) > 0
    assert len(pcm16k) % 2 == 0  # 16-bit aligned


def test_pcm24k_output_becomes_ulaw_8k():
    pcm_24k = b"\x00\x00" * 2400  # 100ms @ 24k
    r = Resampler(24000, 8000)
    ulaw = pcm24k_to_ulaw8k(pcm_24k, r)
    # 24k->8k is 1/3 the samples, ulaw is 1 byte/sample => ~800 bytes
    assert 750 <= len(ulaw) <= 850


def test_resampler_state_persists_no_error_across_chunks():
    r = Resampler(8000, 16000)
    a = r.resample(b"\x01\x00" * 400)
    b = r.resample(b"\x01\x00" * 400)
    assert len(a) > 0 and len(b) > 0
