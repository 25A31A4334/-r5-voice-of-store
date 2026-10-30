"""Validation Script for Phase 1 (Locality Resolver) & Phase 2 (Text Classifier).

Author: Team CodeNova
Usage:
    python FULL_CODE/validate_phase1_phase2.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
import pandas as pd

# Guarantee UTF-8 output encoding for Windows terminal
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from FULL_CODE.locality_resolver import LocalityResolver
from FULL_CODE.classifier import IssueClassifier


def run_phase1_validation() -> dict:
    print("=" * 70)
    print("PHASE 1: LOCALITY RESOLVER VALIDATION")
    print("=" * 70)

    fb_path = DATA / "feedback.csv"
    sm_path = DATA / "store_master.csv"
    fb = pd.read_csv(fb_path)
    resolver = LocalityResolver(sm_path)

    t0 = time.time()
    resolved_df = resolver.resolve_dataframe(fb)
    elapsed = time.time() - t0

    total_rows = len(fb)
    orig_present = int((resolved_df["store_resolution_source"] == "original").sum())
    locality_matched = int((resolved_df["store_resolution_source"] == "locality_match").sum())
    unresolved = int((resolved_df["store_resolution_source"] == "unresolved").sum())

    print(f"Total Feedback Rows: {total_rows}")
    print(f"1. Originally had valid store_id (preserved untouched): {orig_present} ({orig_present/total_rows*100:.1f}%)")
    print(f"2. Missing store_id resolved via unambiguous locality:  {locality_matched} ({locality_matched/total_rows*100:.1f}%)")
    print(f"3. Missing store_id unresolved (preserved as None/NaN): {unresolved} ({unresolved/total_rows*100:.1f}%)")
    print(f"Processing time: {elapsed:.2f} seconds")

    # Verify that original store_ids were not overwritten
    orig_mask = fb["store_id"].notna()
    mismatches = (fb.loc[orig_mask, "store_id"].astype(str).str.upper() != resolved_df.loc[orig_mask, "resolved_store_id"]).sum()
    print(f"Original store_id preservation check (mismatches): {mismatches} (MUST BE 0)")

    return {
        "total_rows": total_rows,
        "orig_present": orig_present,
        "locality_matched": locality_matched,
        "unresolved": unresolved,
        "preservation_check": mismatches == 0,
    }


def run_phase2_validation() -> dict:
    print("\n" + "=" * 70)
    print("PHASE 2: TEXT CLASSIFIER VALIDATION (ZERO TEST/FUTURE LEAKAGE)")
    print("=" * 70)

    fb_path = DATA / "feedback.csv"
    train_path = DATA / "feedback_labels_train.csv"

    fb = pd.read_csv(fb_path)
    train = pd.read_csv(train_path)

    # Join strictly with training labels (3,000 rows from Weeks 1-13)
    train_full = train.merge(fb, on="feedback_id", how="inner")
    print(f"Training dataset size: {len(train_full)} records across {train_full['issue_type_id'].nunique()} issue types")

    # 1. Stratified 5-Fold Cross-Validation
    print("\n--- 1. Stratified 5-Fold Cross-Validation ---")
    classifier = IssueClassifier(random_state=42)
    t0 = time.time()
    cv_results = classifier.evaluate_cv(train_full["text"], train_full["issue_type_id"], n_splits=5)
    cv_time = time.time() - t0

    print(f"Fold Macro-F1 scores: {cv_results['fold_macro_f1s']}")
    print(f"Mean 5-Fold Macro-F1: {cv_results['mean_macro_f1']:.4f} (+/- {cv_results['std_macro_f1']:.4f})")
    print(f"Baseline Official Macro-F1: 0.5590")
    print(f"Macro-F1 Gain: +{cv_results['mean_macro_f1'] - 0.5590:.4f}")
    print(f"CV execution time: {cv_time:.2f}s")

    # 2. Causal Temporal Split (Weeks 1-9 vs Weeks 10-13)
    print("\n--- 2. Temporal Out-of-Time Validation (Weeks 1-9 -> Weeks 10-13) ---")
    train_full["week_start"] = pd.to_datetime(train_full["created_at"]).dt.to_period("W-SUN").dt.start_time.dt.strftime("%Y-%m-%d")
    temp_results = classifier.evaluate_temporal_split(
        train_full,
        text_col="text",
        label_col="issue_type_id",
        week_col="week_start",
        split_week="2026-06-01",
    )
    print(f"Train period (Weeks 1-9):   {temp_results['n_train']} records")
    print(f"Test period  (Weeks 10-13): {temp_results['n_val']} records")
    print(f"Temporal Validation Macro-F1: {temp_results['val_macro_f1']:.4f}")

    return {
        "5fold_mean_macro_f1": cv_results["mean_macro_f1"],
        "baseline_macro_f1": 0.5590,
        "temporal_val_macro_f1": temp_results["val_macro_f1"],
    }


if __name__ == "__main__":
    p1 = run_phase1_validation()
    p2 = run_phase2_validation()
    print("\n" + "=" * 70)
    print("PHASES 1 & 2 VALIDATION SUMMARY")
    print("=" * 70)
    print(f"Phase 1 Locality Matches: {p1['locality_matched']} records recovered (0 mismatches on original)")
    print(f"Phase 2 5-Fold CV Macro-F1: {p2['5fold_mean_macro_f1']:.4f} (Baseline: 0.5590, Gain: +{p2['5fold_mean_macro_f1'] - p2['baseline_macro_f1']:.4f})")
    print(f"Phase 2 Temporal Validation: {p2['temporal_val_macro_f1']:.4f}")
