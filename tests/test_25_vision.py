"""Tests for app.core.vision — image encoding and multimodal message building.

Run with:
    python -m pytest tests/test_25_vision.py -v --tb=short
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.vision import (
    SUPPORTED_EXTENSIONS,
    build_anthropic_image_block,
    build_gemini_image_part,
    build_multimodal_message,
    build_openai_image_block,
    encode_image,
    extract_image_paths,
    is_image_path,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tiny_png(path: Path) -> None:
    """Write a minimal valid 1×1 white PNG to *path*."""
    # Smallest valid PNG (1×1 white pixel)
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
    )
    path.write_bytes(png_bytes)


# ── is_image_path ─────────────────────────────────────────────────────────────

def test_is_image_path_png():
    assert is_image_path("photo.png") is True


def test_is_image_path_jpg():
    assert is_image_path("snapshot.jpg") is True


def test_is_image_path_jpeg():
    assert is_image_path("image.jpeg") is True


def test_is_image_path_gif():
    assert is_image_path("anim.gif") is True


def test_is_image_path_webp():
    assert is_image_path("modern.webp") is True


def test_is_image_path_non_image():
    assert is_image_path("code.py") is False


def test_is_image_path_text_file():
    assert is_image_path("readme.txt") is False


def test_is_image_path_case_insensitive_upper():
    assert is_image_path("file.JPG") is True


def test_is_image_path_case_insensitive_mixed():
    assert is_image_path("Photo.Png") is True


# ── encode_image ──────────────────────────────────────────────────────────────

def test_encode_image_missing_file():
    with pytest.raises(FileNotFoundError):
        encode_image("/nonexistent/path/image.png")


def test_encode_image_unsupported_extension(tmp_path):
    txt = tmp_path / "file.txt"
    txt.write_text("hello")
    with pytest.raises(ValueError, match="Unsupported image extension"):
        encode_image(str(txt))


def test_encode_image_returns_base64_and_media_type(tmp_path):
    png = tmp_path / "test.png"
    _make_tiny_png(png)
    b64_data, media_type = encode_image(str(png))
    assert media_type == "image/png"
    # Verify it's valid base64
    decoded = base64.b64decode(b64_data)
    assert len(decoded) > 0
    # Verify it round-trips to the original bytes
    assert decoded == png.read_bytes()


def test_encode_image_jpeg_media_type(tmp_path):
    jpg = tmp_path / "photo.jpg"
    # Write a minimal JPEG-like file (just needs to be readable and correct ext)
    jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
    b64_data, media_type = encode_image(str(jpg))
    assert media_type == "image/jpeg"


def test_encode_image_rejects_oversized_file(tmp_path):
    """encode_image should raise ValueError for files over 20 MB."""
    big = tmp_path / "big.png"
    # Write just over 20 MB
    big.write_bytes(b"\x00" * (20 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="too large"):
        encode_image(str(big))


def test_encode_image_exactly_at_limit_passes(tmp_path):
    """A file exactly 20 MB should be accepted."""
    limit = tmp_path / "limit.png"
    limit.write_bytes(b"\x00" * (20 * 1024 * 1024))
    # Should not raise; if it does the test fails naturally
    b64_data, media_type = encode_image(str(limit))
    assert media_type == "image/png"


# ── build_anthropic_image_block ───────────────────────────────────────────────

def test_build_anthropic_image_block_structure(tmp_path):
    png = tmp_path / "a.png"
    _make_tiny_png(png)
    block = build_anthropic_image_block(str(png))
    assert block["type"] == "image"
    assert block["source"]["type"] == "base64"
    assert block["source"]["media_type"] == "image/png"
    assert isinstance(block["source"]["data"], str)
    assert len(block["source"]["data"]) > 0


# ── build_openai_image_block ──────────────────────────────────────────────────

def test_build_openai_image_block_structure(tmp_path):
    png = tmp_path / "b.png"
    _make_tiny_png(png)
    block = build_openai_image_block(str(png))
    assert block["type"] == "image_url"
    url = block["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert block["image_url"]["detail"] == "high"


# ── build_gemini_image_part ───────────────────────────────────────────────────

def test_build_gemini_image_part_structure(tmp_path):
    png = tmp_path / "c.png"
    _make_tiny_png(png)
    part = build_gemini_image_part(str(png))
    assert "inline_data" in part
    assert part["inline_data"]["mime_type"] == "image/png"
    assert isinstance(part["inline_data"]["data"], str)
    assert len(part["inline_data"]["data"]) > 0


# ── extract_image_paths ───────────────────────────────────────────────────────

def test_extract_image_paths_finds_png():
    paths = extract_image_paths("check @/tmp/photo.png please")
    # On Windows /tmp/photo.png gets resolved but that's fine — we just check the name
    assert len(paths) == 1
    assert paths[0].endswith("photo.png")


def test_extract_image_paths_ignores_non_image():
    paths = extract_image_paths("see @/tmp/file.py and @/tmp/code.txt")
    assert paths == []


def test_extract_image_paths_multiple(tmp_path):
    # Use real temp paths so they can be resolved; extraction doesn't require existence
    p1 = str(tmp_path / "img1.png").replace("\\", "/")
    p2 = str(tmp_path / "img2.jpg").replace("\\", "/")
    text = f"images @{p1} and @{p2}"
    paths = extract_image_paths(text)
    assert len(paths) == 2


def test_extract_image_paths_deduplicates(tmp_path):
    p = str(tmp_path / "img.png").replace("\\", "/")
    text = f"@{p} and again @{p}"
    paths = extract_image_paths(text)
    assert len(paths) == 1


def test_extract_image_paths_quoted_path():
    paths = extract_image_paths('@"/tmp/my image.webp"')
    assert len(paths) == 1
    assert paths[0].endswith("my image.webp")


def test_extract_image_paths_no_at():
    paths = extract_image_paths("just a plain message with no at-references")
    assert paths == []


# ── build_multimodal_message ──────────────────────────────────────────────────

def test_build_multimodal_message_anthropic(tmp_path):
    png = tmp_path / "d.png"
    _make_tiny_png(png)
    msg = build_multimodal_message("describe this", [str(png)], "anthropic")
    assert msg["role"] == "user"
    content = msg["content"]
    assert isinstance(content, list)
    # First block is text
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "describe this"
    # Second block is image
    assert content[1]["type"] == "image"
    assert content[1]["source"]["type"] == "base64"


def test_build_multimodal_message_openai(tmp_path):
    png = tmp_path / "e.png"
    _make_tiny_png(png)
    msg = build_multimodal_message("what is this", [str(png)], "openai")
    assert msg["role"] == "user"
    content = msg["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"


def test_build_multimodal_message_gemini(tmp_path):
    png = tmp_path / "f.png"
    _make_tiny_png(png)
    msg = build_multimodal_message("analyze image", [str(png)], "gemini")
    assert msg["role"] == "user"
    content = msg["content"]
    assert isinstance(content, list)
    # First part is text dict
    assert "text" in content[0]
    # Second part is inline_data
    assert "inline_data" in content[1]


def test_build_multimodal_message_ollama_graceful_fallback(tmp_path):
    """Ollama provider: content must be a plain string, not a list."""
    png = tmp_path / "g.png"
    _make_tiny_png(png)
    msg = build_multimodal_message("hello", [str(png)], "ollama")
    assert msg["role"] == "user"
    assert isinstance(msg["content"], str)
    assert msg["content"] == "hello"


def test_build_multimodal_message_meta_graceful_fallback(tmp_path):
    """Meta (local Ollama) provider: also returns plain text."""
    png = tmp_path / "h.png"
    _make_tiny_png(png)
    msg = build_multimodal_message("hello meta", [str(png)], "meta")
    assert msg["role"] == "user"
    assert isinstance(msg["content"], str)


def test_build_multimodal_message_no_images_anthropic():
    """No images — content list still works but only has the text block."""
    msg = build_multimodal_message("just text", [], "anthropic")
    assert msg["role"] == "user"
    assert isinstance(msg["content"], list)
    assert msg["content"][0]["text"] == "just text"


def test_build_multimodal_message_unknown_provider(tmp_path):
    """Unknown provider falls back to plain text gracefully."""
    png = tmp_path / "i.png"
    _make_tiny_png(png)
    msg = build_multimodal_message("text", [str(png)], "unknown_provider")
    assert msg["role"] == "user"
    assert isinstance(msg["content"], str)


def test_build_multimodal_message_missing_image_anthropic():
    """Missing image file: error is embedded in a text block, not raised."""
    msg = build_multimodal_message("text", ["/nonexistent/img.png"], "anthropic")
    content = msg["content"]
    # Should have text block + error block, not crash
    assert isinstance(content, list)
    texts = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    assert "Image errors" in texts or "not found" in texts.lower()
