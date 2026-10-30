"""Locality Resolver Module for R5 — Voice-of-Store Engine.

Author: Team CodeNova
Purpose:
    Maps unassigned customer feedback (online reviews, app comments) to specific
    stores using locality mentions in the text, adhering strictly to the evaluator's
    Evidence Rule.

Safety & Precision:
    - Never overwrites an existing valid store_id.
    - Matches only unambiguous localities (exactly 1 match in the text).
    - If multiple localities or zero localities match, the record remains unresolved (None/NaN).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
import pandas as pd


class LocalityResolver:
    """Resolves store localities from text using store_master data."""

    def __init__(self, store_master_path: str | Path | None = None) -> None:
        if store_master_path is None:
            store_master_path = Path(__file__).resolve().parents[1] / "data" / "store_master.csv"
        self.store_master_path = Path(store_master_path)
        self.locality_to_store_id: dict[str, str] = {}
        self.store_id_to_locality: dict[str, str] = {}
        self.store_id_to_name: dict[str, str] = {}
        self.patterns: list[tuple[str, str, re.Pattern]] = []
        self._load_store_master()

    def _load_store_master(self) -> None:
        """Loads store master and compiles safe boundary regex patterns."""
        if not self.store_master_path.exists():
            raise FileNotFoundError(f"Store master file not found: {self.store_master_path}")

        sm = pd.read_csv(self.store_master_path, dtype=str)
        # Sort by locality name length descending so longer phrases match first if needed
        localities_raw = []
        for _, r in sm.iterrows():
            store_id = str(r["store_id"]).strip().upper()
            store_name = str(r["store_name"]).strip()
            # Locality is the name following 'Saffron <Format> ', matching evaluate.py convention
            # e.g. 'Saffron Market Kothrud' -> 'Kothrud'
            parts = store_name.split(" ", 2)
            locality = parts[2].strip() if len(parts) >= 3 else store_name
            localities_raw.append((store_id, store_name, locality))

        # Sort longer names first
        localities_raw.sort(key=lambda x: len(x[2]), reverse=True)

        for store_id, store_name, locality in localities_raw:
            loc_lower = locality.lower()
            self.locality_to_store_id[loc_lower] = store_id
            self.store_id_to_locality[store_id] = loc_lower
            self.store_id_to_name[store_id] = store_name

            # Build regex pattern with word boundaries.
            # Handles optional dot for names like 'T. Nagar' -> allows 't. nagar' or 't nagar'
            escaped = re.escape(loc_lower).replace(r"\.", r"\.?")
            # Also allow optional hyphen / space variation if applicable
            pattern = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
            self.patterns.append((store_id, loc_lower, pattern))

    def resolve_text(self, text: str | None) -> tuple[Optional[str], Optional[str], str]:
        """Resolves a single text to a store_id.

        Returns:
            (store_id, locality, status) where status is:
            - 'unique_match': exactly 1 locality matched
            - 'ambiguous': > 1 localities matched (unresolved)
            - 'no_match': 0 localities matched (unresolved)
        """
        if not text or not isinstance(text, str):
            return None, None, "no_match"

        clean_text = text.strip()
        matched = []
        for store_id, loc_name, pattern in self.patterns:
            if pattern.search(clean_text):
                matched.append((store_id, loc_name))

        if len(matched) == 1:
            return matched[0][0], matched[0][1], "unique_match"
        elif len(matched) > 1:
            # Check if all matched entities point to the same store_id
            unique_store_ids = set(m[0] for m in matched)
            if len(unique_store_ids) == 1:
                return matched[0][0], matched[0][1], "unique_match"
            return None, None, "ambiguous"
        else:
            return None, None, "no_match"

    def resolve_dataframe(self, df: pd.DataFrame, text_col: str = "text", store_col: str = "store_id") -> pd.DataFrame:
        """Augments dataframe with resolved_store_id without altering original store_id.

        Adds two columns:
            - 'resolved_store_id': contains original store_id if present; otherwise unambiguous locality match
            - 'store_resolution_source': 'original', 'locality_match', or 'unresolved'
        """
        out = df.copy()
        resolved = []
        sources = []

        for _, row in out.iterrows():
            orig_store = row.get(store_col)
            # If original store_id is valid and non-empty
            if pd.notna(orig_store) and str(orig_store).strip() and str(orig_store).strip() != "nan":
                resolved.append(str(orig_store).strip().upper())
                sources.append("original")
            else:
                text_val = row.get(text_col, "")
                store_id, _, status = self.resolve_text(text_val)
                if status == "unique_match" and store_id:
                    resolved.append(store_id)
                    sources.append("locality_match")
                else:
                    resolved.append(None)
                    sources.append("unresolved")

        out["resolved_store_id"] = resolved
        out["store_resolution_source"] = sources
        return out


if __name__ == "__main__":
    resolver = LocalityResolver()
    print(f"Loaded {len(resolver.locality_to_store_id)} store localities.")

    # Test cases
    test_samples = [
        ("Visited the Kothrud branch yesterday, good service.", "Should match Kothrud (ST-4H2KQ)"),
        ("Saffron Express T. Nagar had long lines today.", "Should match T. Nagar"),
        ("I went to Kothrud and Baner stores today.", "Ambiguous match (multiple stores) -> should remain unresolved"),
        ("Great app experience, easy checkout.", "No store locality -> should remain unresolved"),
    ]

    for sample_text, note in test_samples:
        sid, loc, st = resolver.resolve_text(sample_text)
        print(f"\nText: '{sample_text}'")
        print(f"Result: store_id={sid}, locality={loc}, status={st} ({note})")
