"""Whisper API client - supports OpenRouter (JSON + base64) and OpenAI-style
multipart endpoints (Ollama, LocalAI, faster-whisper-server)."""

import base64

import httpx

from .config import Config


class WhisperAPIError(Exception):
    """Error communicating with Whisper API."""

    pass


class WhisperClient:
    """Client for OpenAI-compatible Whisper API."""

    def __init__(self, config: Config):
        self.config = config

    def _request_kwargs(self, audio_data: bytes) -> dict:
        """Build httpx post kwargs for the configured request format.

        - "multipart": OpenAI-style file upload (Ollama, LocalAI, OpenAI,
          faster-whisper-server).
        - "openrouter" (default): JSON body with base64-encoded audio.
        """
        headers = {}
        api_key = self.config.resolve_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        if self.config.api_format == "multipart":
            files = {"file": ("audio.wav", audio_data, "audio/wav")}
            data = {"model": self.config.model, "response_format": "json"}
            if self.config.language:
                data["language"] = self.config.language
            return {"headers": headers, "files": files, "data": data}

        # OpenRouter: JSON body with base64-encoded audio.
        headers["Content-Type"] = "application/json"
        payload = {
            "model": self.config.model,
            "input_audio": {
                "data": base64.b64encode(audio_data).decode("ascii"),
                "format": "wav",
            },
            "language": self.config.language,
        }
        return {"headers": headers, "json": payload}

    async def transcribe(self, audio_data: bytes) -> str:
        """
        Send audio to Whisper API and return transcription.

        Args:
            audio_data: WAV audio data as bytes

        Returns:
            Transcribed text
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.config.api_url,
                    **self._request_kwargs(audio_data),
                )

                if response.status_code != 200:
                    raise WhisperAPIError(f"API returned {response.status_code}: {response.text}")

                result = response.json()
                return result.get("text", "").strip()

        except httpx.TimeoutException:
            raise WhisperAPIError("Request timed out")
        except httpx.RequestError as e:
            raise WhisperAPIError(f"Request failed: {e}")
        except Exception as e:
            raise WhisperAPIError(f"Unexpected error: {e}")

    def transcribe_sync(self, audio_data: bytes) -> str:
        """Synchronous version of transcribe."""
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.config.api_url,
                    **self._request_kwargs(audio_data),
                )

                if response.status_code == 401:
                    raise WhisperAPIError("Unauthorized - check your API key in settings")
                elif response.status_code == 403:
                    raise WhisperAPIError("Access denied - check your API key permissions")
                elif response.status_code == 404:
                    raise WhisperAPIError("API endpoint not found - check your API URL")
                elif response.status_code >= 500:
                    raise WhisperAPIError("Server error - try again later")
                elif response.status_code != 200:
                    raise WhisperAPIError(f"API error ({response.status_code})")

                result = response.json()
                return result.get("text", "").strip()

        except httpx.TimeoutException:
            raise WhisperAPIError("Request timed out - server may be busy")
        except httpx.ConnectError:
            raise WhisperAPIError("Could not connect - check internet/API URL")
        except httpx.RequestError as e:
            raise WhisperAPIError(f"Connection error: {e}")
