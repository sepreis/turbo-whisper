"""Audio recording functionality."""

import io
import re
import subprocess
import sys
import threading
import wave
from collections import deque

import numpy as np
import pyaudio

from .config import Config


def get_pipewire_sources() -> list[dict]:
    """Get PipeWire audio input sources with friendly names."""
    try:
        result = subprocess.run(
            ["pactl", "list", "sources"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []

        sources = []
        current = {}

        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Source #"):
                if current and current.get("is_input"):
                    sources.append(current)
                current = {"id": line.split("#")[1]}
            elif line.startswith("Name:"):
                current["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Description:"):
                desc = line.split(":", 1)[1].strip()
                current["description"] = desc
                current["is_input"] = (
                    "alsa_input" in current.get("name", "") and "Monitor" not in desc
                )

        if current and current.get("is_input"):
            sources.append(current)

        return sources
    except Exception:
        return []


class AudioRecorder:
    """Records audio from microphone with level monitoring."""

    def __init__(self, config: Config):
        self.config = config
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.frames: list[bytes] = []
        self.is_recording = False
        self.level_callback = None
        self._actual_sample_rate = config.sample_rate
        self.waveform_buffer = deque(maxlen=100)
        self._record_thread = None

    def get_input_devices(self) -> list[dict]:
        """Get list of available input devices."""
        # Try PipeWire first (Linux)
        if sys.platform.startswith("linux"):
            pw_sources = get_pipewire_sources()
            if pw_sources:
                return [
                    {
                        "index": src["id"],
                        "name": src["description"],
                        "pipewire_name": src["name"],
                        "channels": 2,
                        "sample_rate": 48000,
                    }
                    for src in pw_sources
                ]

        # Fallback to PyAudio
        devices = []
        for i in range(self.audio.get_device_count()):
            try:
                info = self.audio.get_device_info_by_index(i)
                if info["maxInputChannels"] > 0:
                    devices.append(
                        {
                            "index": i,
                            "name": info["name"],
                            "channels": info["maxInputChannels"],
                            "sample_rate": int(info["defaultSampleRate"]),
                        }
                    )
            except Exception:
                pass
        return devices

    def _resolve_input_device(self) -> int | None:
        """Resolve the configured mic to a PyAudio input-device index.

        Matches config.input_device_name as a case-insensitive substring against
        available input devices, preferring PipeWire-routed nodes over raw ALSA
        'hw:' devices (which can't resample to the recording rate). Returns None
        to use the system default when unset or unmatched.
        """
        name = (self.config.input_device_name or "").strip()
        # The settings UI appends a display-only sample-rate suffix, e.g.
        # "JBL Quantum Stream Mono (48000Hz)". It is not part of any real device
        # name, so leaving it in makes every substring match fail.
        name = re.sub(r"\s*\(\d+\s*Hz\)\s*$", "", name)
        if not name:
            return None
        matches = []
        for i in range(self.audio.get_device_count()):
            try:
                info = self.audio.get_device_info_by_index(i)
            except Exception:
                continue
            if info.get("maxInputChannels", 0) < 1:
                continue
            dev_name = str(info.get("name", ""))
            if name.lower() in dev_name.lower():
                matches.append((i, dev_name))
        if not matches:
            print(f"Input device '{name}' not found; using system default")
            return None
        for i, dev_name in matches:
            if "(hw:" not in dev_name:
                return i
        return matches[0][0]

    def _open_stream(self, device_index: int | None) -> tuple:
        """Open an input stream at the configured sample rate.

        A specific device node may not support the configured rate. We do NOT
        fall back to the device's native rate: some PipeWire nodes accept a
        native-rate open() but then corrupt the heap when read (an uncatchable
        crash), so opening them is never safe. Instead, fall back to the
        system-default device, which resamples to the configured rate reliably.
        Returns (stream, actual_rate).
        """

        def _open(idx):
            return self.audio.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                input_device_index=idx,
                frames_per_buffer=self.config.chunk_size,
            )

        rate = self.config.sample_rate
        if device_index is not None:
            try:
                return _open(device_index), rate
            except OSError:
                print(
                    "Selected mic can't record at "
                    f"{rate} Hz; using system default instead"
                )
        return _open(None), rate

    def start(self, level_callback=None) -> None:
        """Start recording audio."""
        if self.is_recording:
            return

        self.level_callback = level_callback
        self.frames = []
        self.is_recording = True

        # Honor the configured mic (resolved by name); None = system default.
        device_index = self._resolve_input_device()
        self.stream, self._actual_sample_rate = self._open_stream(device_index)

        self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._record_thread.start()

    def _record_loop(self) -> None:
        """Recording loop."""
        frame_count = 0
        while self.is_recording and self.stream:
            try:
                data = self.stream.read(self.config.chunk_size, exception_on_overflow=False)
                self.frames.append(data)
                frame_count += 1

                audio_data = np.frombuffer(data, dtype=np.int16)
                level = np.abs(audio_data).mean() / 32768.0

                self.waveform_buffer.append(level)

                if self.level_callback:
                    self.level_callback(level, list(self.waveform_buffer))

            except Exception as e:
                print(f"Recording error: {e}")
                break

    def stop(self) -> bytes:
        """Stop recording and return WAV data."""
        self.is_recording = False

        if self._record_thread:
            self._record_thread.join(timeout=1.0)

        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(self.config.channels)
            wf.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))
            wf.setframerate(self._actual_sample_rate)
            wf.writeframes(b"".join(self.frames))

        return wav_buffer.getvalue()

    def cleanup(self) -> None:
        """Clean up audio resources."""
        self.is_recording = False
        if self.stream:
            self.stream.close()
        self.audio.terminate()
