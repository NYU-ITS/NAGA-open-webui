"""Shared request formats for transient multimodal answer-model inputs."""

AUDIO_INPUT_FORMAT_GEMINI_DATA_URL = "gemini_data_url"
AUDIO_INPUT_FORMAT_OPENAI = "openai_input_audio"

SUPPORTED_AUDIO_INPUT_FORMATS = frozenset(
    {
        AUDIO_INPUT_FORMAT_GEMINI_DATA_URL,
        AUDIO_INPUT_FORMAT_OPENAI,
    }
)


__all__ = [
    "AUDIO_INPUT_FORMAT_GEMINI_DATA_URL",
    "AUDIO_INPUT_FORMAT_OPENAI",
    "SUPPORTED_AUDIO_INPUT_FORMATS",
]
