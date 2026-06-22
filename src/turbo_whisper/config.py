"""Configuration management for Turbo Whisper."""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TypedDict


def _default_hotkey() -> list[str]:
    """Return platform-appropriate default hotkey."""
    import sys
    if sys.platform == "win32":
        # Alt+Space conflicts with Windows window menu
        # Ctrl+Shift+Space conflicts with various apps
        # Win+Shift+V conflicts with clipboard history
        return ["f8"]
    else:
        return ["alt", "space"]


class HistoryEntry(TypedDict, total=False):
    """A history entry with text, timestamp, and optional audio file."""

    text: str
    timestamp: str  # ISO format
    audio_file: str  # Filename (not full path) of WAV recording


@dataclass
class Config:
    """Application configuration."""

    # API settings
    api_url: str = "https://whisper.weeksfamily.me/v1/audio/transcriptions"
    api_key: str = ""
    model: str = "openai/whisper-large-v3-turbo"  # OpenRouter STT model id

    # Hotkey settings (using pynput key names)
    # Default: F8 on Windows (Alt+Space conflicts with window menu)
    #          Alt+Space on Linux/macOS
    hotkey: list[str] = field(default_factory=_default_hotkey)

    # Audio settings
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    input_device_index: int | str | None = None  # None = system default, str for PipeWire source ID
    input_device_name: str = ""  # For display purposes

    # UI settings
    waveform_color: str = "#84cc16"  # KnowAll.ai lime green
    background_color: str = "#1a1a2e"
    window_width: int = 260
    window_height: int = 48  # Compact single-row recording pill

    # Behavior
    auto_paste: bool = True
    copy_to_clipboard: bool = True
    language: str = "en"
    typing_delay_ms: int = 5  # Milliseconds between keystrokes (increase if terminal freezes)

    # Claude Code integration
    claude_integration: bool = True  # Enable integration server for Claude Code
    claude_integration_port: int = 7878  # Port for integration HTTP server
    claude_wait_timeout: float = 30.0  # Max seconds to wait for Claude ready signal

    # History (recent transcriptions)
    history: list[HistoryEntry] = field(default_factory=list)
    history_max: int = 20
    store_recordings: bool = True  # Save audio files with transcriptions

    def _load_env_file(self) -> None:
        """Load KEY=VALUE pairs from <config_dir>/.env into os.environ.

        Does not overwrite variables already present in the environment.
        """
        env_path = self.get_config_path().parent / ".env"
        if not env_path.exists():
            return
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :]
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")

    def resolve_api_key(self) -> str:
        """Return the API key, falling back to <config_dir>/.env or the environment.

        Lets the key live in OPEN_ROUTER_API_KEY / OPENROUTER_API_KEY /
        WHISPER_API_KEY instead of config.json. Resolved at request time so the
        key is never written back to disk by save().
        """
        self._load_env_file()
        return (
            self.api_key
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPEN_ROUTER_API_KEY")
            or os.environ.get("WHISPER_API_KEY")
            or ""
        )

    def get_recordings_dir(self) -> Path:
        """Get the directory for storing audio recordings."""
        import sys
        if sys.platform == "win32":
            config_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        recordings_dir = config_dir / "turbo-whisper" / "recordings"
        recordings_dir.mkdir(parents=True, exist_ok=True)
        return recordings_dir

    def add_to_history(self, text: str, audio_file: str | None = None) -> None:
        """Add a transcription to history.

        Args:
            text: The transcribed text
            audio_file: Optional filename of the WAV recording
        """
        if text and text.strip():
            # Remove if already exists (move to top) and delete old audio
            for i, entry in enumerate(self.history):
                entry_text = entry["text"] if isinstance(entry, dict) else entry
                if entry_text == text:
                    # Delete old audio file if it exists
                    old_audio = entry.get("audio_file") if isinstance(entry, dict) else None
                    if old_audio:
                        old_path = self.get_recordings_dir() / old_audio
                        if old_path.exists():
                            old_path.unlink()
                    self.history.pop(i)
                    break
            # Add to front with timestamp
            entry: HistoryEntry = {
                "text": text,
                "timestamp": datetime.now().isoformat(),
            }
            if audio_file:
                entry["audio_file"] = audio_file
            self.history.insert(0, entry)
            # Trim to max size and clean up old recordings
            self._cleanup_old_recordings()
            self.save()

    def _cleanup_old_recordings(self) -> None:
        """Remove old recordings beyond history_max limit."""
        # Get entries that will be removed
        removed_entries = self.history[self.history_max :]
        self.history = self.history[: self.history_max]

        # Delete audio files for removed entries
        recordings_dir = self.get_recordings_dir()
        for entry in removed_entries:
            if isinstance(entry, dict) and entry.get("audio_file"):
                audio_path = recordings_dir / entry["audio_file"]
                if audio_path.exists():
                    try:
                        audio_path.unlink()
                    except OSError:
                        pass  # Ignore errors deleting files

    @classmethod
    def get_config_path(cls) -> Path:
        """Get the configuration file path."""
        import sys
        if sys.platform == "win32":
            # Windows: use APPDATA
            config_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            # Linux/macOS: use XDG_CONFIG_HOME
            config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return config_dir / "turbo-whisper" / "config.json"

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from file or create default."""
        config_path = cls.get_config_path()

        if config_path.exists():
            try:
                with open(config_path) as f:
                    data = json.load(f)
                # Migrate old string-based history to new format
                if "history" in data and data["history"]:
                    migrated = []
                    for entry in data["history"]:
                        if isinstance(entry, str):
                            # Old format: just a string
                            migrated.append({"text": entry, "timestamp": ""})
                        else:
                            # New format: dict with text and timestamp
                            migrated.append(entry)
                    data["history"] = migrated
                return cls(**data)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Warning: Could not load config: {e}")

        return cls()

    def save(self) -> None:
        """Save configuration to file."""
        config_path = self.get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w") as f:
            json.dump(self.__dict__, f, indent=2)
