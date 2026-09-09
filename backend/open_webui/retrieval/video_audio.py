"""Best-effort extraction of raw audio aligned to temporal video chunks."""

from __future__ import annotations

import io
import json
import math
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from open_webui.retrieval.embedding.errors import (
    VIDEO_AUDIO_ABSENT,
    VIDEO_AUDIO_EXTRACTION_FAILED,
    VIDEO_AUDIO_FALLBACK_VISUAL_ONLY,
)
from open_webui.utils.otel_instrumentation import add_metric_counter, add_span_event


AUDIO_CHUNKING_VERSION = "video_audio_segments_v2"
AUDIO_EXTRACTION_VERSION = "audio_pcm_s16le_mono_16000_v1"
AUDIO_MIME_TYPE = "audio/wav"
AUDIO_SAMPLE_RATE = 16_000
AUDIO_SAMPLE_WIDTH = 2
AUDIO_CHANNELS = 1

_AUDIO_EXTRACTION_TIMEOUT_SECONDS = 90
_AUDIO_PROBE_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class VideoSegmentWindow:
    index: int
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class AudioSegment:
    segment_index: int
    start_seconds: float
    end_seconds: float
    audio: bytes
    mime_type: str = AUDIO_MIME_TYPE


@dataclass(frozen=True)
class VideoAudioResult:
    segments: tuple[AudioSegment, ...]
    warnings: tuple[str, ...]


def prepare_video_audio(
    *,
    source_bytes: bytes,
    source_sha256: str,
    mime_type: str,
    windows: Sequence[VideoSegmentWindow],
) -> VideoAudioResult:
    """Transcode one video audio stream and slice it on existing chunk bounds.

    Extraction is deliberately best effort. A missing or unreadable audio stream
    returns stable warnings and no audio chunks so visual video ingestion can
    continue unchanged.
    """

    normalized_windows = _validate_windows(windows)
    if not normalized_windows:
        return VideoAudioResult(segments=(), warnings=())

    try:
        with tempfile.TemporaryDirectory(prefix="video-audio-") as temp_dir:
            source_path = Path(temp_dir) / f"source{_video_suffix(mime_type)}"
            wav_path = Path(temp_dir) / "audio.wav"
            source_path.write_bytes(source_bytes)

            if not _has_audio_stream(source_path):
                return _finish(
                    segments=(),
                    warnings=(VIDEO_AUDIO_ABSENT, VIDEO_AUDIO_FALLBACK_VISUAL_ONLY),
                    source_sha256=source_sha256,
                    extraction_outcome="absent",
                )

            wav_bytes = _transcode_audio_wav(source_path, wav_path)
            segments = _slice_wav(wav_bytes, normalized_windows)
            return _finish(
                segments=segments,
                warnings=(),
                source_sha256=source_sha256,
                extraction_outcome="succeeded",
            )
    except Exception as error:
        add_span_event(
            "retrieval.video.audio.extraction_failed",
            {
                "error.type": type(error).__name__,
                "video.source_sha256_prefix": source_sha256[:12],
            },
        )
        return _finish(
            segments=(),
            warnings=(
                VIDEO_AUDIO_EXTRACTION_FAILED,
                VIDEO_AUDIO_FALLBACK_VISUAL_ONLY,
            ),
            source_sha256=source_sha256,
            extraction_outcome="failed",
        )


def _validate_windows(
    windows: Sequence[VideoSegmentWindow],
) -> tuple[VideoSegmentWindow, ...]:
    if isinstance(windows, (str, bytes)) or not isinstance(windows, Sequence):
        raise TypeError("video segment windows must be a sequence")

    normalized: list[VideoSegmentWindow] = []
    seen_indexes: set[int] = set()
    for window in windows:
        if not isinstance(window, VideoSegmentWindow):
            raise TypeError("video segment windows must use VideoSegmentWindow")
        if (
            isinstance(window.index, bool)
            or window.index < 0
            or window.index in seen_indexes
            or not math.isfinite(window.start_seconds)
            or not math.isfinite(window.end_seconds)
            or window.start_seconds < 0
            or window.end_seconds <= window.start_seconds
        ):
            raise ValueError("video segment window is invalid")
        seen_indexes.add(window.index)
        normalized.append(window)
    return tuple(normalized)


def _has_audio_stream(source_path: Path) -> bool:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "json",
            str(source_path),
        ],
        capture_output=True,
        check=False,
        timeout=_AUDIO_PROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise OSError("video audio stream inspection failed")
    payload = json.loads(result.stdout)
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise OSError("video audio stream inspection returned an invalid response")
    return bool(streams)


def _transcode_audio_wav(source_path: Path, wav_path: Path) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(source_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            str(AUDIO_CHANNELS),
            "-ar",
            str(AUDIO_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            "-y",
            str(wav_path),
        ],
        capture_output=True,
        check=False,
        timeout=_AUDIO_EXTRACTION_TIMEOUT_SECONDS,
    )
    if result.returncode != 0 or not wav_path.is_file():
        raise OSError("video audio extraction failed")
    wav_bytes = wav_path.read_bytes()
    if not wav_bytes:
        raise OSError("video audio extraction returned no data")
    return wav_bytes


def _slice_wav(
    wav_bytes: bytes,
    windows: Sequence[VideoSegmentWindow],
) -> tuple[AudioSegment, ...]:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as source_wav:
            if (
                source_wav.getnchannels() != AUDIO_CHANNELS
                or source_wav.getframerate() != AUDIO_SAMPLE_RATE
                or source_wav.getsampwidth() != AUDIO_SAMPLE_WIDTH
                or source_wav.getcomptype() != "NONE"
            ):
                raise ValueError("transcoded audio does not match the PCM contract")
            pcm_bytes = source_wav.readframes(source_wav.getnframes())
    except (EOFError, wave.Error) as error:
        raise ValueError("transcoded audio is not a valid WAV file") from error

    frame_width = AUDIO_CHANNELS * AUDIO_SAMPLE_WIDTH
    complete_length = len(pcm_bytes) - (len(pcm_bytes) % frame_width)
    pcm_bytes = pcm_bytes[:complete_length]
    if not pcm_bytes:
        raise ValueError("transcoded audio contains no PCM frames")

    frame_count = len(pcm_bytes) // frame_width
    segments = []
    for window in windows:
        start_frame = max(0, int(round(window.start_seconds * AUDIO_SAMPLE_RATE)))
        end_frame = max(
            start_frame + 1,
            int(round(window.end_seconds * AUDIO_SAMPLE_RATE)),
        )
        requested_frame_count = end_frame - start_frame
        available_start = min(start_frame, frame_count)
        available_end = min(end_frame, frame_count)
        segment_pcm = pcm_bytes[
            available_start * frame_width : available_end * frame_width
        ]
        missing_frames = requested_frame_count - len(segment_pcm) // frame_width
        if missing_frames > 0:
            segment_pcm += b"\x00" * missing_frames * frame_width

        segments.append(
            AudioSegment(
                segment_index=window.index,
                start_seconds=window.start_seconds,
                end_seconds=window.end_seconds,
                audio=_build_wav(segment_pcm),
            )
        )
    return tuple(segments)


def _build_wav(pcm_bytes: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as segment_wav:
        segment_wav.setnchannels(AUDIO_CHANNELS)
        segment_wav.setsampwidth(AUDIO_SAMPLE_WIDTH)
        segment_wav.setframerate(AUDIO_SAMPLE_RATE)
        segment_wav.writeframes(pcm_bytes)
    return output.getvalue()


def split_pcm_wav(wav_bytes: bytes) -> tuple[bytes, bytes]:
    """Split a canonical PCM WAV into two non-empty, frame-aligned WAVs."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as source_wav:
            if (
                source_wav.getnchannels() != AUDIO_CHANNELS
                or source_wav.getframerate() != AUDIO_SAMPLE_RATE
                or source_wav.getsampwidth() != AUDIO_SAMPLE_WIDTH
                or source_wav.getcomptype() != "NONE"
            ):
                raise ValueError("audio does not match the PCM contract")
            frame_count = source_wav.getnframes()
            pcm_bytes = source_wav.readframes(frame_count)
    except (EOFError, wave.Error) as error:
        raise ValueError("audio is not a valid WAV file") from error
    if frame_count < 2:
        raise ValueError("audio is too short to split")
    frame_width = AUDIO_CHANNELS * AUDIO_SAMPLE_WIDTH
    midpoint = frame_count // 2
    split_at = midpoint * frame_width
    return _build_wav(pcm_bytes[:split_at]), _build_wav(pcm_bytes[split_at:])


def _finish(
    *,
    segments: Sequence[AudioSegment],
    warnings: Sequence[str],
    source_sha256: str,
    extraction_outcome: str,
) -> VideoAudioResult:
    segment_tuple = tuple(segments)
    warning_tuple = tuple(dict.fromkeys(warnings))
    add_metric_counter(
        "retrieval.video.audio_extractions",
        {"outcome": extraction_outcome},
    )
    for _ in segment_tuple:
        add_metric_counter("retrieval.video.audio_chunks_created")
    if VIDEO_AUDIO_FALLBACK_VISUAL_ONLY in warning_tuple:
        add_metric_counter("retrieval.video.audio_fallback_visual_only")
    for warning in warning_tuple:
        add_span_event(
            "retrieval.video.audio.warning",
            {
                "warning.code": warning,
                "video.source_sha256_prefix": source_sha256[:12],
            },
        )
    return VideoAudioResult(segments=segment_tuple, warnings=warning_tuple)


def _video_suffix(mime_type: str) -> str:
    if mime_type == "video/quicktime":
        return ".mov"
    if mime_type == "video/mpeg":
        return ".mpeg"
    return ".mp4"


__all__ = [
    "AUDIO_CHUNKING_VERSION",
    "AUDIO_EXTRACTION_VERSION",
    "split_pcm_wav",
    "AUDIO_MIME_TYPE",
    "AudioSegment",
    "VideoAudioResult",
    "VideoSegmentWindow",
    "prepare_video_audio",
]
