"""Comprehensive Validation Script for Phase 3 (Severity & Actionability).

Author: Team CodeNova
Usage:
    python FULL_CODE/validate_phase3.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import f1_score, classification_report

# Guarantee UTF-8 output encoding for Windows terminal
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from FULL_CODE.locality_resolver import LocalityResolver
from FULL_CODE.classifier import IssueClassifier
from FULL_CODE.severity_engine import SeverityEngine
from FULL_CODE.actionability_engine import ActionabilityEngine


def run_phase3_validation() -> None:
    print("=" * 70)
    print("PHASE 3: SEVERITY & ACTIONABILITY VALIDATION")
    print("=" * 70)

    train_path = ROOT / "data" / "feedback_labels_train.csv"
    fb_path = ROOT / "data" / "feedback.csv"
    train_df = pd.read_csv(train_path)
    fb_df = pd.read_csv(fb_path)

    # Merge strictly on 3,000 training labels
    df = train_df.merge(fb_df, on="feedback_id", how="inner")
    print(f"Dataset Size: {len(df)} records across {df['issue_type_id'].nunique()} issue types")

    # Step 1: Locality resolution for routability
    resolver = LocalityResolver()
    resolved_df = resolver.resolve_dataframe(df)

    # 5-Fold Stratified Cross-Validation on the full classification pipeline
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    fold_issue_f1s = []
    fold_sev_f1s = []
    fold_act_f1s = []
    fold_class_scores = []

    t0 = time.time()
    for fold, (train_idx, val_idx) in enumerate(skf.split(resolved_df, resolved_df["issue_type_id"])):
        train_fold = resolved_df.iloc[train_idx]
        val_fold = resolved_df.iloc[val_idx]

        # 1. Fit models exclusively on training fold
        issue_clf = IssueClassifier(random_state=42)
        issue_clf.fit(train_fold["text"], train_fold["issue_type_id"])

        sev_eng = SeverityEngine(random_state=42)
        sev_eng.fit(train_fold["text"], train_fold["severity"])

        act_eng = ActionabilityEngine(random_state=42)
        act_eng.fit(train_fold["text"], train_fold["actionable"])

        # 2. Predict on validation fold
        val_pred_issues = issue_clf.predict(val_fold["text"])
        val_pred_sevs = sev_eng.predict(val_fold["text"], val_pred_issues)
        val_pred_acts = act_eng.predict(
            val_fold["text"],
            val_fold["resolved_store_id"],
            val_pred_issues,
        )

        # 3. Compute metrics matching official evaluate.py formulas
        issue_f1 = f1_score(val_fold["issue_type_id"], val_pred_issues, average="macro")
        sev_f1 = f1_score(val_fold["severity"], val_pred_sevs, average="weighted")
        act_f1 = f1_score(val_fold["actionable"], val_pred_acts, average="binary")
        class_score = 0.5 * issue_f1 + 0.25 * sev_f1 + 0.25 * act_f1

        fold_issue_f1s.append(issue_f1)
        fold_sev_f1s.append(sev_f1)
        fold_act_f1s.append(act_f1)
        fold_class_scores.append(class_score)

        print(f"Fold {fold+1}: Issue Macro-F1={issue_f1:.4f} | Sev Weighted-F1={sev_f1:.4f} | Act Binary-F1={act_f1:.4f} -> Class Score={class_score:.4f}")

    total_cv_time = time.time() - t0

    # Summary
    print("\n" + "=" * 70)
    print("5-FOLD CROSS-VALIDATION RESULTS")
    print("=" * 70)
    mean_issue = np.mean(fold_issue_f1s)
    mean_sev = np.mean(fold_sev_f1s)
    mean_act = np.mean(fold_act_f1s)
    mean_class = np.mean(fold_class_scores)

    print(f"1. Issue Type Macro-F1:     {mean_issue:.4f}  (Baseline: 0.5590, Gain: +{mean_issue - 0.5590:.4f})")
    print(f"2. Severity Weighted-F1:    {mean_sev:.4f}  (Baseline: 0.4475, Gain: +{mean_sev - 0.4475:.4f})")
    print(f"3. Actionable Binary-F1:    {mean_act:.4f}  (Baseline: 0.7507, Gain: +{mean_act - 0.7507:.4f})")
    print("-" * 70)
    print(f"TOTAL CLASSIFICATION SCORE: {mean_class:.4f}  (Baseline: 0.5791, Gain: +{mean_class - 0.5791:.4f})")
    print(f"Execution Time: {total_cv_time:.2f}s")

    # Temporal Out-of-Time Validation (Weeks 1-9 vs Weeks 10-13)
    print("\n" + "=" * 70)
    print("TEMPORAL OUT-OF-TIME VALIDATION (Weeks 1-9 Train -> Weeks 10-13 Val)")
    print("=" * 70)
    resolved_df["week_start"] = pd.to_datetime(resolved_df["created_at"]).dt.to_period("W-SUN").dt.start_time.dt.strftime("%Y-%m-%d")
    train_mask = resolved_df["week_start"] < "2026-06-01"
    val_mask = resolved_df["week_start"] >= "2026-06-01"

    t_df = resolved_df[train_mask]
    v_df = resolved_df[val_mask]

    t_issue_clf = IssueClassifier(random_state=42).fit(t_df["text"], t_df["issue_type_id"])
    t_sev_eng = SeverityEngine(random_state=42).fit(t_df["text"], t_df["severity"])
    t_act_eng = ActionabilityEngine(random_state=42).fit(t_df["text"], t_df["actionable"])

    temp_val_issues = t_issue_clf.predict(v_df["text"])
    temp_val_sevs = t_sev_eng.predict(v_df["text"], temp_val_issues)
    temp_val_acts = t_act_eng.predict(v_df["text"], v_df["resolved_store_id"], temp_val_issues)

    t_issue_f1 = f1_score(v_df["issue_type_id"], temp_val_issues, average="macro")
    t_sev_f1 = f1_score(v_df["severity"], temp_val_sevs, average="weighted")
    t_act_f1 = f1_score(v_df["actionable"], temp_val_acts, average="binary")
    t_class_score = 0.5 * t_issue_f1 + 0.25 * t_sev_f1 + 0.25 * t_act_f1

    print(f"Training samples (Weeks 1-9):   {len(t_df)}")
    print(f"Validation samples (Weeks 10-13): {len(v_df)}")
    print(f"Out-of-Time Issue Type Macro-F1:     {t_issue_f1:.4f}")
    print(f"Out-of-Time Severity Weighted-F1:    {t_sev_f1:.4f}")
    print(f"Out-of-Time Actionable Binary-F1:    {t_act_f1:.4f}")
    print(f"Out-of-Time Classification Score:    {t_class_score:.4f}")


if __name__ == "__main__":
    run_phase3_validation()
