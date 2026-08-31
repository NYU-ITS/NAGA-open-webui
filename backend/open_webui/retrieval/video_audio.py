"""Best-effort, STT-free audio enrichment for video retrieval."""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from open_webui.retrieval.embedding.errors import (
    VIDEO_AUDIO_ABSENT,
    VIDEO_AUDIO_CAPTION_FAILED,
    VIDEO_AUDIO_CAPTION_MODEL_UNAVAILABLE,
    VIDEO_AUDIO_FALLBACK_VISUAL_ONLY,
    VIDEO_AUDIO_SUBTITLE_EXTRACTION_FAILED,
    VIDEO_AUDIO_SUBTITLE_PARSE_FAILED,
)
from open_webui.retrieval.video_audio_caption import (
    VideoAudioCaptionError,
    VideoAudioCaptionService,
    VideoAudioCaptionUnavailable,
)
from open_webui.utils.otel_instrumentation import add_metric_counter, add_span_event


AUDIO_CHUNKING_VERSION = "audio_v1"
_CACHE_VERSION = "video_audio_cache_v1"
_SUBTITLE_TIMEOUT_SECONDS = 60
_AUDIO_TIMEOUT_SECONDS = 90
_TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]+\}")


@dataclass(frozen=True)
class VideoSegmentWindow:
    index: int
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class AudioSegmentText:
    segment_index: int
    start_seconds: float
    end_seconds: float
    text: str
    content_kind: str
    source_type: str
    source_confidence: float
    caption_model_name: str | None = None


@dataclass(frozen=True)
class VideoAudioResult:
    segments: tuple[AudioSegmentText, ...]
    warnings: tuple[str, ...]
    cache: Mapping[str, Any]


@dataclass(frozen=True)
class _SubtitleCue:
    start_seconds: float
    end_seconds: float
    text: str


def prepare_video_audio(
    *,
    source_bytes: bytes,
    source_sha256: str,
    mime_type: str,
    windows: Sequence[VideoSegmentWindow],
    config: Any,
    admin_email: str,
    cached: Mapping[str, Any] | None = None,
) -> VideoAudioResult:
    """Return subtitle or semantic audio text aligned to video segments.

    Every media/model failure is converted to a stable warning. The caller can
    therefore keep the already-prepared visual chunks indexable.
    """
    if not windows:
        return VideoAudioResult(segments=(), warnings=(), cache={})

    suffix = _video_suffix(mime_type)
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix) as source_file:
            source_file.write(source_bytes)
            source_file.flush()
            streams = _probe_streams(source_file.name)
            return _prepare_from_file(
                source_path=source_file.name,
                source_sha256=source_sha256,
                streams=streams,
                windows=tuple(windows),
                config=config,
                admin_email=admin_email,
                cached=cached,
            )
    except Exception:
        return _finish(
            segments=(),
            warnings=(
                VIDEO_AUDIO_SUBTITLE_EXTRACTION_FAILED,
                VIDEO_AUDIO_FALLBACK_VISUAL_ONLY,
            ),
            cache={},
            source_sha256=source_sha256,
        )


def _prepare_from_file(
    *,
    source_path: str,
    source_sha256: str,
    streams: Sequence[Mapping[str, Any]],
    windows: tuple[VideoSegmentWindow, ...],
    config: Any,
    admin_email: str,
    cached: Mapping[str, Any] | None,
) -> VideoAudioResult:
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    subtitle_streams = [
        stream for stream in streams if stream.get("codec_type") == "subtitle"
    ]
    captioner: VideoAudioCaptionService | None = None
    caption_unavailable = False
    if audio_streams:
        try:
            captioner = VideoAudioCaptionService(config, admin_email)
        except VideoAudioCaptionUnavailable:
            caption_unavailable = True

    stream_fingerprint = _stream_fingerprint((*audio_streams, *subtitle_streams))
    cache_key = _cache_key(
        source_sha256=source_sha256,
        stream_fingerprint=stream_fingerprint,
        windows=windows,
        caption_model_name=captioner.model_name if captioner else "",
        prompt_fingerprint=captioner.prompt_fingerprint if captioner else "",
    )
    cached_result = _read_cache(cached, cache_key)
    if cached_result is not None:
        return _finish(
            segments=cached_result.segments,
            warnings=cached_result.warnings,
            cache=dict(cached or {}),
            source_sha256=source_sha256,
        )

    warnings: list[str] = []
    if not audio_streams:
        warnings.append(VIDEO_AUDIO_ABSENT)

    subtitle_cues: tuple[_SubtitleCue, ...] = ()
    subtitle_source_type = "embedded_subtitle"
    if subtitle_streams:
        subtitle_cues, subtitle_source_type, subtitle_warning = _extract_subtitles(
            source_path, subtitle_streams
        )
        if subtitle_warning:
            warnings.append(subtitle_warning)

    derived: dict[int, AudioSegmentText] = {}
    if subtitle_cues:
        for window in windows:
            text = _text_for_window(subtitle_cues, window)
            if text:
                derived[window.index] = AudioSegmentText(
                    segment_index=window.index,
                    start_seconds=window.start_seconds,
                    end_seconds=window.end_seconds,
                    text=text,
                    content_kind="captioned_subtitle",
                    source_type=subtitle_source_type,
                    source_confidence=0.95,
                )

    uncovered = tuple(window for window in windows if window.index not in derived)
    if uncovered and audio_streams:
        if captioner is None:
            if caption_unavailable:
                warnings.append(VIDEO_AUDIO_CAPTION_MODEL_UNAVAILABLE)
        else:
            try:
                wav_bytes = _extract_audio_wav(source_path)
                add_metric_counter("retrieval.video.audio_caption_calls")
                summaries = captioner.summarize(
                    wav_bytes,
                    tuple(
                        (window.index, window.start_seconds, window.end_seconds)
                        for window in uncovered
                    ),
                )
                for window in uncovered:
                    text = _normalize_text(summaries.get(window.index, ""))
                    if not text:
                        continue
                    derived[window.index] = AudioSegmentText(
                        segment_index=window.index,
                        start_seconds=window.start_seconds,
                        end_seconds=window.end_seconds,
                        text=text,
                        content_kind="captioned_summarized_audio",
                        source_type="transcoded_audio_summary",
                        source_confidence=0.65,
                        caption_model_name=captioner.model_name,
                    )
                if any(window.index not in derived for window in uncovered):
                    warnings.append(VIDEO_AUDIO_CAPTION_FAILED)
            except (VideoAudioCaptionError, OSError, subprocess.SubprocessError):
                warnings.append(VIDEO_AUDIO_CAPTION_FAILED)

    if any(window.index not in derived for window in windows):
        warnings.append(VIDEO_AUDIO_FALLBACK_VISUAL_ONLY)

    segments = tuple(derived[index] for index in sorted(derived))
    warnings_tuple = tuple(dict.fromkeys(warnings))
    cache_value: dict[str, Any] = {}
    transient_failures = {
        VIDEO_AUDIO_CAPTION_FAILED,
        VIDEO_AUDIO_SUBTITLE_EXTRACTION_FAILED,
        VIDEO_AUDIO_SUBTITLE_PARSE_FAILED,
    }
    if not transient_failures.intersection(warnings_tuple):
        cache_value = {
            "version": _CACHE_VERSION,
            "cache_key": cache_key,
            "stream_fingerprint": stream_fingerprint,
            "caption_model_name": captioner.model_name if captioner else None,
            "prompt_fingerprint": captioner.prompt_fingerprint if captioner else None,
            "warnings": list(warnings_tuple),
            "segments": [_segment_to_dict(segment) for segment in segments],
        }
    return _finish(
        segments=segments,
        warnings=warnings_tuple,
        cache=cache_value,
        source_sha256=source_sha256,
    )


def _probe_streams(source_path: str) -> tuple[Mapping[str, Any], ...]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            source_path,
        ],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise OSError("video stream inspection failed")
    payload = json.loads(result.stdout)
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise OSError("video stream inspection returned no streams")
    return tuple(stream for stream in streams if isinstance(stream, Mapping))


def _extract_subtitles(
    source_path: str,
    streams: Sequence[Mapping[str, Any]],
) -> tuple[tuple[_SubtitleCue, ...], str, str | None]:
    ordered = sorted(
        streams,
        key=lambda stream: (
            not bool((stream.get("disposition") or {}).get("default")),
            int(stream.get("index", 0)),
        ),
    )
    extracted_any = False
    for stream in ordered:
        stream_index = stream.get("index")
        if not isinstance(stream_index, int):
            continue
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                source_path,
                "-map",
                f"0:{stream_index}",
                "-f",
                "webvtt",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
            timeout=_SUBTITLE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0 or not result.stdout.strip():
            continue
        extracted_any = True
        cues = _parse_webvtt(result.stdout.decode("utf-8", errors="replace"))
        if cues:
            codec = str(stream.get("codec_name") or "").lower()
            source_type = (
                "embedded_closed_caption"
                if codec in {"eia_608", "eia_708", "cea_608", "cea_708"}
                else "embedded_subtitle"
            )
            return cues, source_type, None
    warning = (
        VIDEO_AUDIO_SUBTITLE_PARSE_FAILED
        if extracted_any
        else VIDEO_AUDIO_SUBTITLE_EXTRACTION_FAILED
    )
    return (), "embedded_subtitle", warning


def _parse_webvtt(value: str) -> tuple[_SubtitleCue, ...]:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[_SubtitleCue] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue
        left, right = line.split("-->", 1)
        try:
            start = _parse_timestamp(left.strip().split()[0])
            end = _parse_timestamp(right.strip().split()[0])
        except (IndexError, ValueError):
            index += 1
            continue
        index += 1
        text_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1
        text = _normalize_text(" ".join(text_lines))
        if text and end > start:
            cues.append(_SubtitleCue(start, end, text))
        index += 1
    return tuple(cues)


def _parse_timestamp(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError("invalid subtitle timestamp")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _text_for_window(
    cues: Sequence[_SubtitleCue], window: VideoSegmentWindow
) -> str:
    values: list[str] = []
    for cue in cues:
        if cue.end_seconds <= window.start_seconds or cue.start_seconds >= window.end_seconds:
            continue
        if not values or values[-1] != cue.text:
            values.append(cue.text)
    return _normalize_text(" ".join(values))


def _extract_audio_wav(source_path: str) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            source_path,
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            "pipe:1",
        ],
        capture_output=True,
        check=False,
        timeout=_AUDIO_TIMEOUT_SECONDS,
    )
    if result.returncode != 0 or not result.stdout:
        raise OSError("audio extraction failed")
    return result.stdout


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    without_tags = _TAG_RE.sub(" ", html.unescape(value))
    return " ".join(without_tags.split()).strip()


def _stream_fingerprint(streams: Sequence[Mapping[str, Any]]) -> str:
    stable = []
    for stream in streams:
        stable.append(
            {
                "index": stream.get("index"),
                "codec_type": stream.get("codec_type"),
                "codec_name": stream.get("codec_name"),
                "channels": stream.get("channels"),
                "sample_rate": stream.get("sample_rate"),
                "language": (stream.get("tags") or {}).get("language"),
                "default": (stream.get("disposition") or {}).get("default"),
            }
        )
    payload = json.dumps(stable, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_key(
    *,
    source_sha256: str,
    stream_fingerprint: str,
    windows: Sequence[VideoSegmentWindow],
    caption_model_name: str,
    prompt_fingerprint: str,
) -> str:
    payload = {
        "version": _CACHE_VERSION,
        "source_sha256": source_sha256,
        "stream_fingerprint": stream_fingerprint,
        "segments": [
            [window.index, window.start_seconds, window.end_seconds]
            for window in windows
        ],
        "caption_model_name": caption_model_name,
        "prompt_fingerprint": prompt_fingerprint,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _read_cache(
    cached: Mapping[str, Any] | None, cache_key: str
) -> VideoAudioResult | None:
    if not isinstance(cached, Mapping) or cached.get("cache_key") != cache_key:
        return None
    raw_segments = cached.get("segments")
    raw_warnings = cached.get("warnings")
    if not isinstance(raw_segments, list) or not isinstance(raw_warnings, list):
        return None
    try:
        segments = tuple(_segment_from_dict(value) for value in raw_segments)
    except (KeyError, TypeError, ValueError):
        return None
    warnings = tuple(value for value in raw_warnings if isinstance(value, str))
    return VideoAudioResult(segments=segments, warnings=warnings, cache=dict(cached))


def _segment_to_dict(segment: AudioSegmentText) -> dict[str, Any]:
    return {
        "segment_index": segment.segment_index,
        "start_seconds": segment.start_seconds,
        "end_seconds": segment.end_seconds,
        "text": segment.text,
        "content_kind": segment.content_kind,
        "source_type": segment.source_type,
        "source_confidence": segment.source_confidence,
        "caption_model_name": segment.caption_model_name,
    }


def _segment_from_dict(value: Mapping[str, Any]) -> AudioSegmentText:
    if not isinstance(value, Mapping):
        raise TypeError("cached audio segment must be an object")
    return AudioSegmentText(
        segment_index=int(value["segment_index"]),
        start_seconds=float(value["start_seconds"]),
        end_seconds=float(value["end_seconds"]),
        text=str(value["text"]),
        content_kind=str(value["content_kind"]),
        source_type=str(value["source_type"]),
        source_confidence=float(value["source_confidence"]),
        caption_model_name=(
            str(value["caption_model_name"])
            if value.get("caption_model_name")
            else None
        ),
    )


def _finish(
    *,
    segments: Sequence[AudioSegmentText],
    warnings: Sequence[str],
    cache: Mapping[str, Any],
    source_sha256: str,
) -> VideoAudioResult:
    segment_tuple = tuple(segments)
    warning_tuple = tuple(dict.fromkeys(warnings))
    for _ in segment_tuple:
        add_metric_counter("retrieval.video.audio_chunks_created")
    for segment in segment_tuple:
        if segment.content_kind == "captioned_subtitle":
            add_metric_counter("retrieval.video.audio_subtitle_hits")
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
    return VideoAudioResult(
        segments=segment_tuple,
        warnings=warning_tuple,
        cache=dict(cache),
    )


def _video_suffix(mime_type: str) -> str:
    if mime_type == "video/quicktime":
        return ".mov"
    if mime_type == "video/mpeg":
        return ".mpeg"
    return Path("source.mp4").suffix


__all__ = [
    "AUDIO_CHUNKING_VERSION",
    "AudioSegmentText",
    "VideoAudioResult",
    "VideoSegmentWindow",
    "prepare_video_audio",
]
