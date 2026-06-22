"""Whisper API client - targets OpenRouter's /audio/transcriptions (JSON + base64)."""

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

    async def transcribe(self, audio_data: bytes) -> str:
        """
        Send audio to Whisper API and return transcription.

        Args:
            audio_data: WAV audio data as bytes

        Returns:
            Transcribed text
        """
        headers = {}
        api_key = self.config.resolve_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # OpenRouter STT expects a JSON body with base64-encoded audio,
        # not OpenAI's multipart file upload. Model id comes from config.
        headers["Content-Type"] = "application/json"
        payload = {
            "model": self.config.model,
            "input_audio": {
                "data": base64.b64encode(audio_data).decode("ascii"),
                "format": "wav",
            },
            "language": self.config.language,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.config.api_url,
                    headers=headers,
                    json=payload,
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
        headers = {}
        api_key = self.config.resolve_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # OpenRouter STT expects a JSON body with base64-encoded audio,
        # not OpenAI's multipart file upload. Model id comes from config.
        headers["Content-Type"] = "application/json"
        payload = {
            "model": self.config.model,
            "input_audio": {
                "data": base64.b64encode(audio_data).decode("ascii"),
                "format": "wav",
            },
            "language": self.config.language,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.config.api_url,
                    headers=headers,
                    json=payload,
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
