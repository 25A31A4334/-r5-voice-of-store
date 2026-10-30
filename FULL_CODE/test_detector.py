"""Verification and Testing Suite for Emerging-Issue Detector (Phase 4).

Author: Team CodeNova
Usage:
    python FULL_CODE/test_detector.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
import pandas as pd
import numpy as np

# Guarantee UTF-8 output encoding for Windows terminal
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import evaluate
from FULL_CODE.locality_resolver import LocalityResolver
from FULL_CODE.classifier import IssueClassifier
from FULL_CODE.severity_engine import SeverityEngine
from FULL_CODE.actionability_engine import ActionabilityEngine
from FULL_CODE.detector import EmergingIssueDetector


def run_detector_tests() -> None:
    print("=" * 70)
    print("PHASE 4: EMERGING-ISSUE DETECTOR TEST & VERIFICATION")
    print("=" * 70)

    feedback_path = ROOT / "data" / "feedback.csv"
    train_path = ROOT / "data" / "feedback_labels_train.csv"
    stores_path = ROOT / "data" / "store_master.csv"
    calendar_path = ROOT / "data" / "week_calendar.csv"
    incident_path = ROOT / "data" / "emerging_incidents_train.csv"

    # Step 1: Train classification pipeline strictly on training data
    print("\n--- 1. Training Classifier Pipeline on Labelled Training Data ---")
    fb = pd.read_csv(feedback_path)
    train = pd.read_csv(train_path)
    full_train = train.merge(fb, on="feedback_id")

    resolver = LocalityResolver(stores_path)
    clf = IssueClassifier(random_state=42).fit(full_train["text"], full_train["issue_type_id"])
    sev_eng = SeverityEngine(random_state=42).fit(full_train["text"], full_train["severity"])
    act_eng = ActionabilityEngine(random_state=42).fit(full_train["text"], full_train["actionable"])

    # Resolve localities cautiously
    resolved_fb = resolver.resolve_dataframe(fb)
    resolved_fb["issue_type_id"] = clf.predict(resolved_fb["text"])
    resolved_fb["severity"] = sev_eng.predict(resolved_fb["text"], resolved_fb["issue_type_id"])
    resolved_fb["actionable"] = act_eng.predict(
        resolved_fb["text"],
        resolved_fb["resolved_store_id"],
        resolved_fb["issue_type_id"],
    )

    preds_df = resolved_fb[["feedback_id", "issue_type_id", "severity", "actionable"]].copy()

    # Step 2: Causal Emerging Incident Detection
    print("\n--- 2. Running Causal Detector Across All Calendar Weeks ---")
    weeks_df = pd.read_csv(calendar_path)
    all_weeks = weeks_df["week_start"].tolist()
    train_weeks = weeks_df[weeks_df["labelled_period"] == "train"]["week_start"].tolist()

    sm_df = pd.read_csv(stores_path)
    store_names = dict(zip(sm_df["store_id"], sm_df["store_name"]))

    detector = EmergingIssueDetector(
        classifier=clf,
        locality_resolver=resolver,
        data_dir=ROOT / "data",
        z_threshold=2.5,
        min_count=3,
        max_flags_per_week=2,
    )

    t0 = time.time()
    # Detect flags strictly causally
    flags_df = detector.detect_flags(
        resolved_fb,
        weeks=all_weeks,
        emit_weeks=all_weeks,
        store_names=store_names,
    )
    detect_time = time.time() - t0
    print(f"Total flags emitted across all 26 weeks: {len(flags_df)} (in {detect_time:.2f}s)")

    # Step 3: Formal Evaluation with Official evaluate.py
    print("\n--- 3. Official Evaluator Scoring on Worked Example (EX-1) ---")
    truth = evaluate.load_truth(train_path)
    incidents = pd.read_csv(incident_path)
    ev = evaluate.Evidence(feedback_path, stores_path)

    # Save test outputs inside FULL_CODE/ for evaluate.py
    test_preds_path = ROOT / "FULL_CODE" / "test_predictions.csv"
    test_flags_path = ROOT / "FULL_CODE" / "test_flags.csv"
    preds_df.to_csv(test_preds_path, index=False)
    flags_df.to_csv(test_flags_path, index=False)

    # Validate predictions & flags format through evaluate.py loaders
    preds_clean = evaluate.load_predictions(test_preds_path)
    flags_clean = evaluate.load_flags(test_flags_path)

    eval_results = evaluate.score(preds_clean, truth, flags_clean, incidents, ev)

    print("\n" + "=" * 70)
    print("OFFICIAL EVALUATION METRICS BREAKDOWN")
    print("=" * 70)
    print(f"Classification Score:      {eval_results['classification_score']:.6f}  (Baseline: 0.579052)")
    print(f"  - Issue Type Macro-F1:   {eval_results['issue_type_macro_f1']:.6f}  (Baseline: 0.559005)")
    print(f"  - Severity Weighted-F1:  {eval_results['severity_weighted_f1']:.6f}  (Baseline: 0.447502)")
    print(f"  - Actionable Binary-F1:  {eval_results['actionable_f1']:.6f}  (Baseline: 0.750696)")
    print("-" * 70)
    print(f"Emerging Issue Metrics (Scored Weeks: {eval_results['scored_weeks']}):")
    print(f"  - Flags in Scored Period: {eval_results['n_flags']}  (Baseline: 27 flags)")
    print(f"  - Valid Flags:            {eval_results['n_flags_valid']}  (Rejected: {eval_results['n_flags_rejected']})")
    print(f"  - Average Flags / Week:   {eval_results['avg_flags_per_week']:.4f}  (Ceiling: 3.0)")
    print(f"  - Flood Factor Penalty:   {eval_results['flood_factor']:.4f}  (1.0 = No penalty)")
    print(f"  - Flag Precision:         {eval_results['flag_precision']:.4f}  (Baseline: 0.0370)")
    print("-" * 70)

    for inc in eval_results["incidents"]:
        print(f"Incident {inc['incident_id']} ({inc['issue_type_id']}):")
        print(f"  - Onset Week:            {inc['onset_week_start']}")
        print(f"  - Naive Detect Week:     {inc['naive_detect_week_start']}")
        print(f"  - CodeNova Detect Week:  {inc['your_first_matching_flag']}")
        print(f"  - Lead Time (Weeks):     +{inc['lead_weeks']} weeks earlier  (Baseline: 0 weeks)")
        print(f"  - Incident Score:        {inc['incident_score']:.6f}  (Baseline: 0.333333)")

    print("-" * 70)
    print(f"Lead Score:                {eval_results['lead_score']:.6f}  (Baseline: 0.333333)")
    print(f"PRIMARY OVERALL SCORE:     {eval_results['primary_score']:.6f}  (Baseline: 0.480764)")
    print(f"Net Primary Improvement:   +{eval_results['primary_score'] - 0.480764:.6f} (+{(eval_results['primary_score'] - 0.480764)/0.480764*100:.1f}%)")
    print("=" * 70)

    # Step 4: Verify Causal Re-Run Interface (--as-of mode)
    print("\n--- 4. Verifying Jury Re-run Interface (--as-of mode) ---")
    test_asof = "2026-05-11"
    target_monday = "2026-05-11"
    cutoff = pd.Timestamp(target_monday) + pd.Timedelta(days=7)
    fb_cutoff = fb[pd.to_datetime(fb["created_at"]) < cutoff]

    asof_flags = detector.detect_flags(
        fb_cutoff,
        weeks=all_weeks,
        emit_weeks=[target_monday],
        store_names=store_names,
    )
    print(f"As-of {test_asof}: Generated {len(asof_flags)} flag(s) using strictly historical data (created_at < {cutoff})")
    for _, fl in asof_flags.iterrows():
        print(f"  -> Flag: Store={fl['store_id']}, Issue={fl['issue_type_id']}, Conf={fl['confidence']}, EvCount={len(fl['evidence_feedback_ids'].split(';'))}")


if __name__ == "__main__":
    run_detector_tests()
