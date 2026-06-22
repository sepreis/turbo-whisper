"""Tests for input-device resolution in AudioRecorder."""

from turbo_whisper.recorder import AudioRecorder


class _FakeAudio:
    """Minimal stand-in for pyaudio.PyAudio used by _resolve_input_device."""

    def __init__(self, devices):
        self._devices = devices

    def get_device_count(self):
        return len(self._devices)

    def get_device_info_by_index(self, i):
        return self._devices[i]


class _Cfg:
    def __init__(self, input_device_name="", sample_rate=16000, channels=1, chunk_size=1024):
        self.input_device_name = input_device_name
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size


def _make_recorder(input_device_name, devices):
    rec = AudioRecorder.__new__(AudioRecorder)
    rec.config = _Cfg(input_device_name)
    rec.audio = _FakeAudio(devices)
    return rec


class _FakeStream:
    def read(self, *a, **k):
        return b"\x00\x00" * 1024

    def stop_stream(self):
        pass

    def close(self):
        pass


class _OpenRecordingAudio(_FakeAudio):
    """Fake PyAudio that records open() calls and rejects given (index, rate) combos."""

    def __init__(self, devices, rejects=()):
        super().__init__(devices)
        self._rejects = set(rejects)
        self.calls = []

    def open(self, *, input_device_index, rate, **kwargs):
        self.calls.append((input_device_index, rate))
        if (input_device_index, rate) in self._rejects:
            raise OSError(-9997, "Invalid sample rate")
        return _FakeStream()


# Mirrors the real device layout seen on the user's machine.
_DEVICES = [
    {"name": "JBL Quantum Stream: USB Audio (hw:1,0)", "maxInputChannels": 2},
    {"name": "JBL Quantum Stream Mono", "maxInputChannels": 1},
    {"name": "sysdefault", "maxInputChannels": 128},
]


def test_saved_name_with_hz_suffix_still_matches():
    """The settings UI saves a '(48000Hz)' display suffix; it must not break matching."""
    rec = _make_recorder("JBL Quantum Stream Mono (48000Hz)", _DEVICES)
    # Index 1 is the PipeWire-routed node (no 'hw:'), preferred over the raw ALSA device.
    assert rec._resolve_input_device() == 1


def test_plain_name_still_matches():
    rec = _make_recorder("JBL Quantum Stream Mono", _DEVICES)
    assert rec._resolve_input_device() == 1


def test_empty_name_uses_system_default():
    rec = _make_recorder("", _DEVICES)
    assert rec._resolve_input_device() is None


def test_unmatched_name_uses_system_default():
    rec = _make_recorder("Nonexistent Mic", _DEVICES)
    assert rec._resolve_input_device() is None


# Devices for open()-fallback tests: index 14 is a 48000-only node like the JBL.
_RATE_DEVICES = [None] * 14 + [
    {"name": "JBL Quantum Stream Mono", "maxInputChannels": 1, "defaultSampleRate": 48000.0},
]


def _open_recorder(rejects):
    rec = AudioRecorder.__new__(AudioRecorder)
    rec.config = _Cfg("JBL Quantum Stream Mono", sample_rate=16000, channels=1, chunk_size=1024)
    rec.audio = _OpenRecordingAudio(_RATE_DEVICES, rejects=rejects)
    return rec


def test_open_stream_uses_configured_rate_when_supported():
    rec = _open_recorder(rejects=())
    stream, rate = rec._open_stream(14)
    assert rate == 16000
    assert rec.audio.calls == [(14, 16000)]


def test_open_stream_falls_back_to_system_default_when_device_rejects_rate():
    """The JBL case: device rejects 16000. Must fall back to system default, never the
    device's native rate (reading that node corrupts the heap)."""
    rec = _open_recorder(rejects={(14, 16000)})
    stream, rate = rec._open_stream(14)
    assert rate == 16000
    # Only the configured rate is ever attempted: on the device, then on default.
    assert rec.audio.calls == [(14, 16000), (None, 16000)]
    assert all(r == 16000 for _, r in rec.audio.calls)


def test_open_stream_system_default_when_no_device_selected():
    rec = _open_recorder(rejects=())
    stream, rate = rec._open_stream(None)
    assert rate == 16000
    assert rec.audio.calls == [(None, 16000)]
