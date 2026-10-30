"""Text Preprocessing Module for R5 — Voice-of-Store Engine.

Author: Team CodeNova
Purpose:
    Lightweight, robust text normalizer tailored for multilingual Indian retail feedback
    (English, Hinglish, transliterated Tamil & Marathi, call-centre transcripts, and SMS shorthand).
"""
from __future__ import annotations

import re


class TextPreprocessor:
    """Preprocesses raw feedback text into clean tokens suitable for TF-IDF."""

    # Repeated characters reduction: e.g. "sooooo" -> "soo", "badddd" -> "badd"
    _REPEAT_PATTERN = re.compile(r"(.)\1{2,}")
    # Whitespace cleanup
    _WHITESPACE_PATTERN = re.compile(r"\s+")

    @classmethod
    def clean_text(cls, text: str | None) -> str:
        """Cleans and standardizes raw text."""
        if not text or not isinstance(text, str):
            return ""

        # Normalize whitespace
        s = cls._WHITESPACE_PATTERN.sub(" ", text).strip()

        # Reduce character elongations (e.g. 'worsttttt' -> 'worstt', 'plssss' -> 'plss')
        s = cls._REPEAT_PATTERN.sub(r"\1\1", s)

        # Standardize call-centre speaker indicators to lower-case tokens
        s = re.sub(r"\bAgent\s*:\s*", "agent: ", s, flags=re.IGNORECASE)
        s = re.sub(r"\bCustomer\s*:\s*", "customer: ", s, flags=re.IGNORECASE)

        return s

    @classmethod
    def extract_metadata_features(cls, row: dict) -> dict:
        """Extracts text length, channel, and rating metadata features."""
        text = str(row.get("text", ""))
        rating = row.get("rating")
        channel = str(row.get("channel", "unknown"))

        return {
            "text_len": len(text),
            "word_count": len(text.split()),
            "channel": channel,
            "has_rating": int(rating is not None and str(rating) != "" and str(rating) != "nan"),
            "rating_val": float(rating) if rating is not None and str(rating) != "" and str(rating) != "nan" else 0.0,
        }
