"""Emerging-Issue Detector Module for R5 — Voice-of-Store Engine.

Author: Team CodeNova
Purpose:
    Causally detects emerging operational incidents at store level before they escalate
    into chain-wide crises. Enforces zero future-data leakage via the as-of Sunday cutoff,
    resolves store localities cautiously, and cites verified feedback IDs as evidence.

Re-run Command Interface (Jury & Evaluation requirement):
    python FULL_CODE/detector.py --feedback {feedback} --as-of {asof} --out {out}
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
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

try:
    from FULL_CODE.locality_resolver import LocalityResolver
    from FULL_CODE.classifier import IssueClassifier
    from FULL_CODE.severity_engine import SeverityEngine
    from FULL_CODE.actionability_engine import ActionabilityEngine
except ImportError:
    from locality_resolver import LocalityResolver
    from classifier import IssueClassifier
    from severity_engine import SeverityEngine
    from actionability_engine import ActionabilityEngine


class EmergingIssueDetector:
    """Causal emerging-issue detector with footfall/severity weighting and evidence citation."""

    NON_ISSUES = {"NI01", "NI02", "NI03"}
    # Store operational issue types (excluding central digital/app issues IT23-IT29)
    STORE_OPERATIONAL_TYPES = {f"IT{i:02d}" for i in range(1, 23)} | {"IT30"}

    def __init__(
        self,
        classifier: IssueClassifier | None = None,
        locality_resolver: LocalityResolver | None = None,
        data_dir: Path | None = None,
        z_threshold: float = 2.5,
        min_count: int = 3,
        max_flags_per_week: int = 2,
    ) -> None:
        self.data_dir = data_dir or DATA
        self.classifier = classifier
        self.locality_resolver = locality_resolver or LocalityResolver(self.data_dir / "store_master.csv")
        self.z_threshold = z_threshold
        self.min_count = min_count
        self.max_flags_per_week = max_flags_per_week

        # Load taxonomy policy floors
        self.high_severity_types = set()
        tax_path = self.data_dir / "issue_taxonomy.csv"
        if tax_path.exists():
            tax = pd.read_csv(tax_path)
            high_rows = tax[tax["policy_severity_floor"] == "high"]
            self.high_severity_types = set(high_rows["issue_type_id"].str.strip().str.upper())

    def _ensure_classifier_trained(self) -> None:
        """Trains classifier if not already provided."""
        if self.classifier is None:
            train_path = self.data_dir / "feedback_labels_train.csv"
            fb_path = self.data_dir / "feedback.csv"
            if not train_path.exists() or not fb_path.exists():
                raise FileNotFoundError(f"Missing training files in {self.data_dir}")

            train_df = pd.read_csv(train_path)
            fb_df = pd.read_csv(fb_path)
            full_train = train_df.merge(fb_df, on="feedback_id")

            self.classifier = IssueClassifier(random_state=42)
            self.classifier.fit(full_train["text"], full_train["issue_type_id"])

    def detect_flags(
        self,
        fb_df: pd.DataFrame,
        weeks: List[str],
        emit_weeks: List[str],
        store_names: Dict[str, str] | None = None,
    ) -> pd.DataFrame:
        """Detects emerging-issue flags across specified emit_weeks strictly causally."""
        self._ensure_classifier_trained()

        # Step 1: Locality resolution (cautiously maps unassigned reviews)
        resolved_fb = self.locality_resolver.resolve_dataframe(fb_df)

        # Step 2: Predict issue categories
        if "issue_type_id" not in resolved_fb.columns or resolved_fb["issue_type_id"].isna().any():
            resolved_fb["issue_type_id"] = self.classifier.predict(resolved_fb["text"])

        # Step 3: Compute calendar week starts (Monday of each week)
        resolved_fb["week_start"] = (
            pd.to_datetime(resolved_fb["created_at"])
            .dt.to_period("W-SUN")
            .dt.start_time.dt.strftime("%Y-%m-%d")
        )

        # Filter to operational issues at known/resolved stores
        valid_mask = (
            (~resolved_fb["issue_type_id"].isin(self.NON_ISSUES))
            & resolved_fb["resolved_store_id"].notna()
        )
        issues = resolved_fb[valid_mask]

        # Group by store, issue_type, and week_start
        counts = (
            issues.groupby(["resolved_store_id", "issue_type_id", "week_start"])
            .size()
            .unstack(fill_value=0)
            .reindex(columns=weeks, fill_value=0)
        )

        # Track evidence feedback_ids (sorted and ;-separated)
        evidence = (
            issues.groupby(["resolved_store_id", "issue_type_id", "week_start"])["feedback_id"]
            .apply(lambda s: ";".join(sorted(s)))
        )

        flags = []
        for i, w in enumerate(weeks):
            # Require at least 4 historical weeks before flagging
            if i < 4 or w not in emit_weeks:
                continue

            # Rolling baseline: up to past 8 weeks strictly prior to current week i
            hist = counts.iloc[:, max(0, i - 8): i]
            cur = counts.iloc[:, i]
            mu = hist.mean(axis=1)
            sd = hist.std(axis=1, ddof=0).clip(lower=1.0)
            z = (cur - mu) / sd

            # Filter candidates exceeding count and z thresholds
            cand = z[(cur >= self.min_count) & (z >= self.z_threshold)].reset_index()
            cand.columns = ["store_id", "issue_type_id", "z"]

            if len(cand) == 0:
                continue

            # Prioritize store-level operational issues and high policy floor issues
            scores = []
            for r in cand.itertuples():
                s = float(r.z)
                # Boost high-severity policy categories (safety, contamination, cold-chain)
                if r.issue_type_id in self.high_severity_types:
                    s *= 1.5
                # Downweight central digital/payment issues if flagged at store level
                if r.issue_type_id not in self.STORE_OPERATIONAL_TYPES:
                    s *= 0.7
                scores.append(s)

            cand["score"] = scores
            cand["store_name"] = cand["store_id"].map(store_names or {}).fillna(cand["store_id"])

            # Sort by weighted score descending, tie-breaking by store name
            cand = cand.sort_values(
                ["score", "store_name", "issue_type_id"],
                ascending=[False, True, True],
                kind="mergesort",
            ).head(self.max_flags_per_week)

            for r in cand.itertuples():
                try:
                    ev_ids = evidence.loc[(r.store_id, r.issue_type_id, w)]
                except KeyError:
                    continue

                id_list = [x.strip() for x in ev_ids.split(";") if x.strip()]
                # Rule check: flag only emitted if at least 2 distinct evidence feedback IDs exist
                if len(id_list) < 2:
                    continue

                confidence = round(min(1.0, max(0.1, float(r.score) / 10.0)), 3)
                flags.append({
                    "as_of_week_start": w,
                    "store_id": r.store_id,
                    "issue_type_id": r.issue_type_id,
                    "confidence": confidence,
                    "evidence_feedback_ids": ev_ids,
                })

        return pd.DataFrame(
            flags,
            columns=["as_of_week_start", "store_id", "issue_type_id", "confidence", "evidence_feedback_ids"],
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="R5 Voice-of-Store Engine Detector (Team CodeNova). "
        "Supports full causal re-run interface."
    )
    parser.add_argument(
        "--feedback",
        default=str(DATA / "feedback.csv"),
        help="Path to feedback CSV file",
    )
    parser.add_argument(
        "--as-of",
        dest="as_of",
        default=None,
        help="YYYY-MM-DD: Any day of the week to flag (normalised to its Monday)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output CSV path for emerging flags",
    )
    args = parser.parse_args()

    # Dynamic reference loading from the folder containing --feedback (for jury evaluation)
    feedback_path = Path(args.feedback).resolve()
    data_dir = feedback_path.parent
    ref = lambda name: data_dir / name if (data_dir / name).exists() else DATA / name

    weeks_df = pd.read_csv(ref("week_calendar.csv"))
    weeks = weeks_df["week_start"].tolist()

    sm_df = pd.read_csv(ref("store_master.csv"))
    store_names = dict(zip(sm_df["store_id"], sm_df["store_name"]))

    fb_df = pd.read_csv(feedback_path, dtype={"store_id": str})

    detector = EmergingIssueDetector(data_dir=data_dir)

    if args.as_of:
        # Causal Monday normalisation
        target_ts = pd.Timestamp(args.as_of)
        monday = (target_ts - pd.Timedelta(days=target_ts.weekday())).normalize()
        # Strictly before next Monday 00:00:00 = Sunday 23:59:59 (no future data)
        cutoff = monday + pd.Timedelta(days=7)
        fb_filtered = fb_df[pd.to_datetime(fb_df["created_at"]) < cutoff]

        monday_str = monday.strftime("%Y-%m-%d")
        flags = detector.detect_flags(
            fb_filtered,
            weeks=weeks,
            emit_weeks=[monday_str],
            store_names=store_names,
        )

        out_path = Path(args.out or "R5_emerging_flags_asof.csv")
        flags.to_csv(out_path, index=False)
        print(f"As-of {monday.date()}: Wrote {len(flags)} flags using {len(fb_filtered)} records to {out_path}")
        return

    # If run without --as-of, compute across all weeks
    flags = detector.detect_flags(
        fb_df,
        weeks=weeks,
        emit_weeks=weeks,
        store_names=store_names,
    )
    out_path = Path(args.out or "R5_emerging_flags.csv")
    flags.to_csv(out_path, index=False)
    print(f"Full Run: Wrote {len(flags)} emerging flags to {out_path}")


if __name__ == "__main__":
    main()
