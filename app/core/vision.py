"""Vision input helpers — encode images for LLM vision APIs.

Supported providers: anthropic, openai, gemini
Supported formats: PNG, JPEG, GIF, WEBP (what the APIs accept)
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# Keywords that identify Ollama models with vision capability.
# Matched against the lowercased model name (substring match).
_OLLAMA_VISION_KEYWORDS: frozenset[str] = frozenset({
    "llava", "bakllava", "moondream", "llava-phi3", "minicpm-v",
    "llava-llama", "llava-mistral", "phi3-vision", "idefics",
})

_MEDIA_TYPES: dict[str, str] = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}

_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB — Anthropic limit

# Matches @"/path/to/file", @'/path/to/file', or @/path/to/file
_AT_PATH_RE = re.compile(r'@"([^"]+)"|@\'([^\']+)\'|@(\S+)')


# ── Ollama vision capability detection ───────────────────────────────────────

def ollama_model_has_vision(model_name: str) -> bool:
    """Return True if *model_name* is a known Ollama model with vision support.

    Detection is done via substring matching against known vision-capable model
    name keywords (case-insensitive).  False negatives are possible for new or
    custom models; callers can fall back to the plain-text path in that case.
    """
    lower = model_name.lower()
    return any(kw in lower for kw in _OLLAMA_VISION_KEYWORDS)


# ── Core helpers ──────────────────────────────────────────────────────────────

def is_image_path(path: str) -> bool:
    """Return True if *path* has a supported image extension (case-insensitive)."""
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def encode_image(path: str) -> tuple[str, str]:
    """Read an image file and base64-encode it.

    Returns:
        (base64_data, media_type) — e.g. ("iVBOR...", "image/png")

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the extension is not supported or the file exceeds 20 MB.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Image file not found: {path}")

    ext = p.suffix.lower()
    if ext not in _MEDIA_TYPES:
        raise ValueError(
            f"Unsupported image extension '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    file_size = p.stat().st_size
    if file_size > _MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image file is too large ({file_size / 1_048_576:.1f} MB). "
            "Maximum allowed size is 20 MB."
        )

    raw = p.read_bytes()
    b64_data = base64.b64encode(raw).decode("ascii")
    media_type = _MEDIA_TYPES[ext]
    return b64_data, media_type


# ── Provider-specific block builders ─────────────────────────────────────────

def build_anthropic_image_block(path: str) -> dict:
    """Return an Anthropic-format image content block for *path*."""
    b64_data, media_type = encode_image(path)
    return {
        "type": "image",
        "source": {
            "type":       "base64",
            "media_type": media_type,
            "data":       b64_data,
        },
    }


def build_openai_image_block(path: str) -> dict:
    """Return an OpenAI-format image_url content block for *path*."""
    b64_data, media_type = encode_image(path)
    return {
        "type": "image_url",
        "image_url": {
            "url":    f"data:{media_type};base64,{b64_data}",
            "detail": "high",
        },
    }


def build_gemini_image_part(path: str) -> dict:
    """Return a Gemini-format inline_data part for *path*."""
    b64_data, media_type = encode_image(path)
    return {
        "inline_data": {
            "mime_type": media_type,
            "data":      b64_data,
        },
    }


# ── Path extraction ───────────────────────────────────────────────────────────

def extract_image_paths(text: str) -> list[str]:
    """Find @path references in *text* that point to image files.

    Returns a list of absolute path strings for each @reference whose
    extension is in SUPPORTED_EXTENSIONS.  Non-image @paths are ignored.
    """
    image_paths: list[str] = []
    seen: set[str] = set()

    for m in _AT_PATH_RE.finditer(text):
        raw = m.group(1) or m.group(2) or m.group(3)
        if not raw:
            continue
        p = Path(raw).expanduser()
        # Make absolute — if not already, resolve relative to cwd
        if not p.is_absolute():
            p = Path(os.getcwd()) / p
        resolved = str(p)
        if resolved in seen:
            continue
        if is_image_path(raw):
            seen.add(resolved)
            image_paths.append(resolved)

    return image_paths


# ── Multimodal message builder ────────────────────────────────────────────────

def build_multimodal_message(
    text: str,
    image_paths: list[str],
    provider: str,
    model_name: str = "",
) -> dict:
    """Build a properly formatted user message with mixed text + image content.

    For Ollama providers the message degrades gracefully to plain text unless
    the model is known to support vision (detected via *model_name*).  Callers
    never need to branch on provider before calling this function.

    Args:
        text:        The text portion of the message (already @-expanded).
        image_paths: List of absolute paths to image files.
        provider:    One of "anthropic", "openai", "gemini", "groq", "ollama".
        model_name:  Optional model identifier used for capability detection
                     (currently used to detect Ollama vision models).

    Returns:
        A dict with "role" and "content" keys ready to append to a messages list.
    """
    # Ollama — use OpenAI-compatible format only when the model supports vision;
    # otherwise degrade gracefully to a plain text message.
    if provider in ("ollama", "meta"):
        if ollama_model_has_vision(model_name):
            # Ollama's /api/chat accepts the same OpenAI image_url format.
            errors: list[str] = []
            content_ol: list[dict] = [{"type": "text", "text": text}]
            for path in image_paths:
                try:
                    content_ol.append(build_openai_image_block(path))
                except (FileNotFoundError, ValueError) as exc:
                    errors.append(str(exc))
            if errors:
                content_ol.append(
                    {"type": "text", "text": f"[Image errors: {'; '.join(errors)}]"}
                )
            return {"role": "user", "content": content_ol}
        # Vision not supported by this model — return plain text
        return {"role": "user", "content": text}

    errors: list[str] = []

    if provider == "anthropic":
        content: list[dict] = [{"type": "text", "text": text}]
        for path in image_paths:
            try:
                content.append(build_anthropic_image_block(path))
            except (FileNotFoundError, ValueError) as exc:
                errors.append(str(exc))
        if errors:
            content.append({"type": "text", "text": f"[Image errors: {'; '.join(errors)}]"})
        return {"role": "user", "content": content}

    elif provider in ("openai", "groq"):
        content_oa: list[dict] = [{"type": "text", "text": text}]
        for path in image_paths:
            try:
                content_oa.append(build_openai_image_block(path))
            except (FileNotFoundError, ValueError) as exc:
                errors.append(str(exc))
        if errors:
            content_oa.append({"type": "text", "text": f"[Image errors: {'; '.join(errors)}]"})
        return {"role": "user", "content": content_oa}

    elif provider == "gemini":
        # Gemini uses a "parts" list — text part + inline_data parts
        parts: list[dict] = [{"text": text}]
        for path in image_paths:
            try:
                parts.append(build_gemini_image_part(path))
            except (FileNotFoundError, ValueError) as exc:
                errors.append(str(exc))
        if errors:
            parts.append({"text": f"[Image errors: {'; '.join(errors)}]"})
        return {"role": "user", "content": parts}

    else:
        # Unknown provider — fall back to plain text
        return {"role": "user", "content": text}
