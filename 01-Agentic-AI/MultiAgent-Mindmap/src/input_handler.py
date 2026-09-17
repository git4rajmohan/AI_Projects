"""Input handlers for extracting text from files, YouTube URLs, and raw text."""

import re
from pathlib import Path
from typing import Union

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter


def extract_from_file(uploaded_file) -> str:
    """Read text content from an uploaded file (.txt or .md).

    Handles UTF-8 encoding with fallback to latin-1 for legacy files.
    """
    # Streamlit UploadedFile has a .read() method that returns bytes
    raw = uploaded_file.read()
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, AttributeError):
            continue
    # If bytes decoding fails entirely, try string path
    return str(raw)


def extract_from_text(raw_text: str) -> str:
    """Passthrough for raw pasted text."""
    return raw_text.strip()


def _extract_video_id(url: str) -> str:
    """Parse a YouTube video ID from various URL formats.

    Supports:
      - https://www.youtube.com/watch?v=VIDEO_ID
      - https://youtu.be/VIDEO_ID
      - https://www.youtube.com/shorts/VIDEO_ID
      - https://m.youtube.com/watch?v=VIDEO_ID
      - Bare 11-char video IDs
    """
    patterns = [
        r"(?:youtube\.com/watch\?v=)([\w-]{11})",       # watch?v=
        r"(?:youtu\.be/)([\w-]{11})",                    # youtu.be/
        r"(?:youtube\.com/shorts/)([\w-]{11})",          # shorts/
        r"(?:youtube\.com/embed/)([\w-]{11})",           # embed/
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    # Bare video ID
    if re.fullmatch(r"[\w-]{11}", url.strip()):
        return url.strip()
    raise ValueError(f"Could not extract video ID from URL: {url}")


def extract_from_youtube(url: str) -> str:
    """Fetch a YouTube video transcript and return it as plain text.

    Args:
        url: A YouTube URL or bare 11-character video ID.

    Returns:
        The full transcript as a single string.

    Raises:
        ValueError: If the video ID can't be parsed.
        Exception: If the transcript is unavailable (disabled, not found, etc.).
    """
    video_id = _extract_video_id(url)
    transcript = YouTubeTranscriptApi().fetch(video_id)
    formatter = TextFormatter()
    return formatter.format_transcript(transcript)