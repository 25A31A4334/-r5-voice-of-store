"""End-to-End Pipeline Runner for R5 — Voice-of-Store Engine.

Author: Team CodeNova
Purpose:
    Executes the entire CodeNova solution pipeline:
    1. Trains multilingual IssueClassifier on labelled training data.
    2. Trains SeverityEngine enforcing taxonomy floors and critical hazard rules.
    3. Trains ActionabilityEngine implementing the official 3-part actionability logic.
    4. Cautiously resolves store localities for unassigned reviews.
    5. Predicts all 39,769 feedback records for R5_predictions.csv.
    6. Runs EmergingIssueDetector to generate verified causal flags for R5_emerging_flags.csv.
    7. Writes the exact jury detector command into detector_cmd.txt.

Safety:
    Outputs to a designated directory (default: FULL_CODE/phase5_candidate/) without
    touching the original baseline or official submission files.
"""
from __future__ import annotations

import argparse
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
from FULL_CODE.severity_engine import SeverityEngine
from FULL_CODE.actionability_engine import ActionabilityEngine
from FULL_CODE.detector import EmergingIssueDetector


def run_pipeline(
    feedback_path: Path = DATA / "feedback.csv",
    train_labels_path: Path = DATA / "feedback_labels_train.csv",
    stores_path: Path = DATA / "store_master.csv",
    taxonomy_path: Path = DATA / "issue_taxonomy.csv",
    calendar_path: Path = DATA / "week_calendar.csv",
    output_dir: Path = ROOT / "FULL_CODE" / "phase5_candidate",
) -> dict:
    t0 = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("CODENOVA R5 FULL PIPELINE RUNNER")
    print(f"Target Output Directory: {output_dir}")
    print("=" * 70)

    # 1. Load Data
    print("\n[Step 1/6] Loading data files...")
    fb_df = pd.read_csv(feedback_path, dtype={"store_id": str})
    train_df = pd.read_csv(train_labels_path)
    sm_df = pd.read_csv(stores_path)
    weeks_df = pd.read_csv(calendar_path)
    all_weeks = weeks_df["week_start"].tolist()
    store_names = dict(zip(sm_df["store_id"], sm_df["store_name"]))
    print(f"Loaded {len(fb_df)} feedback records, {len(train_df)} training labels, {len(sm_df)} stores.")

    # 2. Train Models strictly on labelled training data
    print("\n[Step 2/6] Training models on labelled training sample (Weeks 1-13)...")
    full_train = train_df.merge(fb_df, on="feedback_id", how="inner")

    issue_clf = IssueClassifier(random_state=42)
    issue_clf.fit(full_train["text"], full_train["issue_type_id"])

    sev_eng = SeverityEngine(taxonomy_path=taxonomy_path, random_state=42)
    sev_eng.fit(full_train["text"], full_train["severity"])

    act_eng = ActionabilityEngine(random_state=42)
    act_eng.fit(full_train["text"], full_train["actionable"])
    print("Models successfully trained.")

    # 3. Locality Resolution across all records
    print("\n[Step 3/6] Resolving store localities for unassigned feedback...")
    resolver = LocalityResolver(stores_path)
    resolved_fb = resolver.resolve_dataframe(fb_df)
    n_recovered = (resolved_fb["store_resolution_source"] == "locality_match").sum()
    print(f"Locality resolution complete: {n_recovered} unassigned reviews mapped to stores.")

    # 4. Generate Predictions for all 39,769 feedback records
    print("\n[Step 4/6] Generating predictions across all 39,769 feedback records...")
    resolved_fb["issue_type_id"] = issue_clf.predict(resolved_fb["text"])
    resolved_fb["severity"] = sev_eng.predict(resolved_fb["text"], resolved_fb["issue_type_id"])
    resolved_fb["actionable"] = act_eng.predict(
        resolved_fb["text"],
        resolved_fb["resolved_store_id"],
        resolved_fb["issue_type_id"],
    )

    pred_cols = ["feedback_id", "issue_type_id", "severity", "actionable"]
    preds_df = resolved_fb[pred_cols].copy()
    preds_out = output_dir / "R5_predictions.csv"
    preds_df.to_csv(preds_out, index=False)
    print(f"Wrote {preds_out} ({len(preds_df)} rows).")

    # 5. Detect Emerging Issues Causally
    print("\n[Step 5/6] Detecting emerging-issue flags causally...")
    detector = EmergingIssueDetector(
        classifier=issue_clf,
        locality_resolver=resolver,
        data_dir=DATA,
        z_threshold=2.5,
        min_count=3,
        max_flags_per_week=2,
    )

    flags_df = detector.detect_flags(
        resolved_fb,
        weeks=all_weeks,
        emit_weeks=all_weeks,
        store_names=store_names,
    )
    flags_out = output_dir / "R5_emerging_flags.csv"
    flags_df.to_csv(flags_out, index=False)
    print(f"Wrote {flags_out} ({len(flags_df)} flags).")

    # 6. Write Detector Re-Run Command
    print("\n[Step 6/6] Writing detector_cmd.txt...")
    cmd_text = "python FULL_CODE/detector.py --feedback {feedback} --as-of {asof} --out {out}\n"
    cmd_out = output_dir / "detector_cmd.txt"
    cmd_out.write_text(cmd_text, encoding="utf-8")
    print(f"Wrote {cmd_out}.")

    elapsed = time.time() - t0
    print("\n" + "=" * 70)
    print(f"PIPELINE COMPLETED SUCCESSFULLY IN {elapsed:.2f} SECONDS")
    print(f"Generated Files:")
    print(f"  1. {preds_out} ({len(preds_df)} records)")
    print(f"  2. {flags_out} ({len(flags_df)} flags)")
    print(f"  3. {cmd_out}")
    print("=" * 70)

    return {
        "output_dir": output_dir,
        "n_predictions": len(preds_df),
        "n_flags": len(flags_df),
        "elapsed_seconds": round(elapsed, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="CodeNova R5 Pipeline Runner")
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "FULL_CODE" / "phase5_candidate"),
        help="Target output directory for candidate files",
    )
    args = parser.parse_args()
    run_pipeline(output_dir=Path(args.out_dir))


if __name__ == "__main__":
    main()
