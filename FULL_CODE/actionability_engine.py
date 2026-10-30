"""Actionability Classification Module for R5 — Voice-of-Store Engine.

Author: Team CodeNova
Purpose:
    Implements the official 3-part Actionability guideline:
    Actionable = 1 if and only if:
        1. Real issue: category in IT01–IT30 (not praise/chatter/spam NI01–NI03).
        2. Specific: contains concrete what/where/when details, rather than a generic rant.
        3. Routable: store is known (via store_id or locality named in text), OR category
           is an online/app/delivery/payment/refund/loyalty issue (IT23–IT29) that does
           not require a store.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion
from sklearn.svm import LinearSVC


class ActionabilityEngine:
    """Classifies feedback actionability strictly adhering to the 3-part official guideline."""

    NON_ISSUES = {"NI01", "NI02", "NI03"}
    DIGITAL_OR_DELIVERY = {"IT23", "IT24", "IT25", "IT26", "IT27", "IT28", "IT29"}

    def __init__(self, random_state: int = 42) -> None:
        self.random_state = random_state
        self.word_vec = TfidfVectorizer(ngram_range=(1, 2), max_features=8000, sublinear_tf=True)
        self.char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_features=12000, sublinear_tf=True)
        self.feature_union = FeatureUnion([("word", self.word_vec), ("char", self.char_vec)])
        self.specificity_classifier = LinearSVC(C=1.0, random_state=self.random_state)
        self.is_fitted = False

    def is_routable(self, store_id: Any, issue_type_id: str) -> bool:
        """Determines if record satisfies Rule 3 (Routability)."""
        tid = str(issue_type_id).strip().upper()
        # Digital and delivery categories do not need a store to be routed
        if tid in self.DIGITAL_OR_DELIVERY:
            return True
        # Otherwise requires a valid non-empty store_id
        if pd.notna(store_id) and str(store_id).strip() and str(store_id).strip() != "nan":
            return True
        return False

    def is_real_issue(self, issue_type_id: str) -> bool:
        """Determines if record satisfies Rule 1 (Real issue)."""
        tid = str(issue_type_id).strip().upper()
        return tid not in self.NON_ISSUES

    def fit(self, texts: pd.Series | List[str], actionable_labels: pd.Series | np.ndarray) -> "ActionabilityEngine":
        """Fits specificity classifier on labelled training data."""
        clean_texts = [str(t) if pd.notna(t) else "" for t in texts]
        X = self.feature_union.fit_transform(clean_texts)
        self.specificity_classifier.fit(X, actionable_labels)
        self.is_fitted = True
        return self

    def predict_single(self, text: str, store_id: Any, issue_type_id: str) -> int:
        """Predicts actionability (0 or 1) for a single record."""
        # Rule 1: Must be a real issue
        if not self.is_real_issue(issue_type_id):
            return 0

        # Rule 3: Must be routable
        if not self.is_routable(store_id, issue_type_id):
            return 0

        # Rule 2: Must be specific
        if self.is_fitted:
            X = self.feature_union.transform([str(text)])
            pred_specific = int(self.specificity_classifier.predict(X)[0])
            return pred_specific
        else:
            return 1 if len(str(text)) > 30 else 0

    def predict(
        self,
        texts: pd.Series | List[str],
        store_ids: pd.Series | List[Any],
        issue_type_ids: pd.Series | List[str],
    ) -> np.ndarray:
        """Batch predicts actionability across all records enforcing all 3 rules."""
        clean_texts = [str(t) if pd.notna(t) else "" for t in texts]
        s_arr = list(store_ids)
        i_arr = [str(x).strip().upper() for x in issue_type_ids]

        # Specificity predictions from model
        if self.is_fitted:
            X = self.feature_union.transform(clean_texts)
            specific_preds = self.specificity_classifier.predict(X)
        else:
            specific_preds = np.array([1 if len(t) > 30 else 0 for t in clean_texts])

        final_actionable = []
        for is_spec, sid, tid in zip(specific_preds, s_arr, i_arr):
            rule1 = self.is_real_issue(tid)
            rule3 = self.is_routable(sid, tid)

            if rule1 and rule3 and (is_spec == 1):
                final_actionable.append(1)
            else:
                final_actionable.append(0)

        return np.array(final_actionable, dtype=int)
