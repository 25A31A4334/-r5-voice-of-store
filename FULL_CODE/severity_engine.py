"""Severity Classification & Policy Enforcement Module for R5 — Voice-of-Store Engine.

Author: Team CodeNova
Purpose:
    Implements the official Severity Annotation Guideline:
        Severity = max(policy_floor, impact)
    - If policy floor is 'high' (safety, allergens, hygiene, staff misconduct),
      severity is at least 'high', regardless of volume.
    - If imminent danger or actual harm (hospital, injury, severe allergic reaction,
      assault, food poisoning), severity is 'critical'.
    - If category is a non-issue (NI01-NI03), severity is always 'low'.
    - For all other issues, impact is learned from the labelled training data
      and can be 'low', 'medium', or 'high'.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion
from sklearn.svm import LinearSVC


class SeverityEngine:
    """Classifies severity respecting official policy floors and critical rules."""

    ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    INV_ORDER = {0: "low", 1: "medium", 2: "high", 3: "critical"}

    # Multilingual triggers for critical actual harm / imminent danger
    CRITICAL_REGEX = re.compile(
        r"hospital|doctor|icu|emergency|admit|infections?|poisoning|beemar|bimar|"
        r"aajari|pot bighadle|potala infection|vomit|vaanthi|ultee?|rashes|anaphylax|"
        r"allergic reaction|swelling|breathing|chok|suffocat|swallowed|pin|glass piece|"
        r"kaanch|wire shock|electric|fire|assault|haath pakad|hathapai|marpeet|police",
        re.IGNORECASE,
    )

    NON_ISSUES = {"NI01", "NI02", "NI03"}

    def __init__(
        self,
        taxonomy_path: str | Path | None = None,
        random_state: int = 42,
    ) -> None:
        if taxonomy_path is None:
            taxonomy_path = Path(__file__).resolve().parents[1] / "data" / "issue_taxonomy.csv"
        self.taxonomy_path = Path(taxonomy_path)
        self.random_state = random_state

        self.policy_floors: dict[str, str] = {}
        self._load_taxonomy()

        self.word_vec = TfidfVectorizer(ngram_range=(1, 2), max_features=8000, sublinear_tf=True)
        self.char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_features=12000, sublinear_tf=True)
        self.feature_union = FeatureUnion([("word", self.word_vec), ("char", self.char_vec)])
        self.classifier = LinearSVC(C=1.0, random_state=self.random_state)
        self.is_fitted = False

    def _load_taxonomy(self) -> None:
        """Loads policy floors from issue_taxonomy.csv."""
        if not self.taxonomy_path.exists():
            raise FileNotFoundError(f"Taxonomy file not found: {self.taxonomy_path}")
        tax = pd.read_csv(self.taxonomy_path)
        for _, r in tax.iterrows():
            tid = str(r["issue_type_id"]).strip().upper()
            floor = str(r.get("policy_severity_floor", "low")).strip().lower()
            self.policy_floors[tid] = floor

    def fit(self, texts: pd.Series | List[str], severities: pd.Series | np.ndarray) -> "SeverityEngine":
        """Fits impact classifier on labelled training data."""
        clean_texts = [str(t) if pd.notna(t) else "" for t in texts]
        X = self.feature_union.fit_transform(clean_texts)
        self.classifier.fit(X, severities)
        self.is_fitted = True
        return self

    def predict_single(self, text: str, issue_type_id: str) -> str:
        """Predicts severity for a single record enforcing policy rules."""
        issue_type_id = str(issue_type_id).strip().upper()

        # Rule 1: Non-issues are always 'low'
        if issue_type_id in self.NON_ISSUES:
            return "low"

        # Determine policy floor
        floor = self.policy_floors.get(issue_type_id, "low")
        floor_val = self.ORDER.get(floor, 0)

        # Check for critical actual harm triggers if floor is high
        if floor == "high" and self.CRITICAL_REGEX.search(text):
            return "critical"

        # Predict learned impact from text
        if self.is_fitted:
            X = self.feature_union.transform([text])
            raw_pred = self.classifier.predict(X)[0]
            impact_val = self.ORDER.get(raw_pred, 0)
        else:
            impact_val = floor_val

        # Rule 2: max(policy_floor, impact)
        final_val = max(floor_val, impact_val)
        return self.INV_ORDER[final_val]

    def predict(
        self,
        texts: pd.Series | List[str],
        issue_type_ids: pd.Series | List[str],
    ) -> np.ndarray:
        """Batch predicts severity enforcing policy rules across all records."""
        clean_texts = [str(t) if pd.notna(t) else "" for t in texts]
        t_arr = np.array(clean_texts)
        i_arr = np.array([str(x).strip().upper() for x in issue_type_ids])

        if self.is_fitted:
            X = self.feature_union.transform(clean_texts)
            raw_preds = self.classifier.predict(X)
        else:
            raw_preds = np.array(["low"] * len(clean_texts))

        final_severities = []
        for raw, tid, txt in zip(raw_preds, i_arr, t_arr):
            if tid in self.NON_ISSUES:
                final_severities.append("low")
                continue

            floor = self.policy_floors.get(tid, "low")
            floor_val = self.ORDER.get(floor, 0)

            if floor == "high" and self.CRITICAL_REGEX.search(txt):
                final_severities.append("critical")
                continue

            impact_val = self.ORDER.get(raw, 0)
            final_val = max(floor_val, impact_val)
            final_severities.append(self.INV_ORDER[final_val])

        return np.array(final_severities)
