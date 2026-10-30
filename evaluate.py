#!/usr/bin/env python3
"""R5 — Voice-of-Store Engine: official scorer (TalentAP Mega Hackathon 2026).

Usage (from the package folder):
    python evaluate.py --submission submission/R5_predictions.csv --truth data/feedback_labels_train.csv [--out score.json]

Optional:
    --flags      path to R5_emerging_flags.csv   (default: next to the predictions file)
    --incidents  path to the incident key         (default: next to the truth file; see find_incidents())
    --feedback   path to data/feedback.csv        (default: data/feedback.csv next to this script; used to check flag evidence)
    --stores     path to data/store_master.csv    (default: next to this script)

Needs only Python >= 3.9, numpy and pandas. Exit code 2 = your submission has a format problem (message explains how to fix it).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ------------------------------------------------------------------------------------------------ constants (also in README)
W_CLASSIFICATION = 0.6            # primary = 0.6 * classification + 0.4 * lead_score
W_LEAD = 0.4
W_ISSUE_MACRO_F1 = 0.5            # classification = 0.5 * macro-F1(issue type) + 0.25 * weighted-F1(severity) + 0.25 * F1(actionable=1)
W_SEVERITY_WEIGHTED_F1 = 0.25
W_ACTIONABLE_F1 = 0.25
LEAD_MIN = -2                     # lead (weeks) is clipped to [LEAD_MIN, LEAD_MAX]; an incident you never flag counts as LEAD_MIN
LEAD_MAX = 4
FLAG_BUDGET_PER_WEEK = 3          # more than 3 flags per week on average scales the lead score down by 3 / avg_flags_per_week
HALF_WEEKS = 13                   # lead time is scored on the 13-week half that holds the incidents of the truth file
                                  # (weeks 1-13 for the public train truth, weeks 14-26 for the hidden test truth);
                                  # flags outside that half are ignored and avg_flags_per_week = flags inside the half / 13
PERIOD_START = dt.date(2026, 3, 30)   # Monday of week 1
N_WEEKS = 26
WEEK_STARTS = [(PERIOD_START + dt.timedelta(weeks=i)).isoformat() for i in range(N_WEEKS)]
SEVERITIES = ["low", "medium", "high", "critical"]
ISSUE_TYPES = [f"IT{i:02d}" for i in range(1, 31)] + ["NI01", "NI02", "NI03"]
PRED_COLS = ["feedback_id", "issue_type_id", "severity", "actionable"]
FLAG_COLS = ["as_of_week_start", "store_id", "issue_type_id", "confidence", "evidence_feedback_ids"]
EVIDENCE_MIN = 2                  # a flag counts only if it cites >= 2 valid evidence feedback_ids (see check_evidence)
HERE = Path(__file__).resolve().parent
MISSING = "__MISSING__"


class FormatError(Exception):
    pass


def fail(msg: str) -> None:
    print("\n" + "=" * 78 + "\nSUBMISSION FORMAT ERROR\n" + "=" * 78 + f"\n{msg}\n", file=sys.stderr)
    sys.exit(2)


# ------------------------------------------------------------------------------------------------ metrics
def f1_per_class(y_true: np.ndarray, y_pred: np.ndarray, labels) -> dict:
    out = {}
    for c in labels:
        tp = int(np.sum((y_true == c) & (y_pred == c)))
        fp = int(np.sum((y_true != c) & (y_pred == c)))
        fn = int(np.sum((y_true == c) & (y_pred != c)))
        out[c] = (2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) > 0 else 0.0
    return out


def macro_f1(y_true, y_pred) -> float:
    labels = sorted(set(y_true.tolist()))
    f = f1_per_class(y_true, y_pred, labels)
    return float(np.mean([f[c] for c in labels]))


def weighted_f1(y_true, y_pred) -> float:
    labels = sorted(set(y_true.tolist()))
    f = f1_per_class(y_true, y_pred, labels)
    w = np.array([np.sum(y_true == c) for c in labels], float)
    return float(np.sum(w * np.array([f[c] for c in labels])) / w.sum())


def binary_f1(y_true, y_pred) -> float:
    tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    fn = int(np.sum((y_true == 1) & (y_pred == 0)))
    return 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0


# ------------------------------------------------------------------------------------------------ loading / validation
def read_csv(path: Path, what: str) -> pd.DataFrame:
    if not path.exists():
        raise FormatError(f"{what} file not found: {path}")
    if path.stat().st_size == 0:
        raise FormatError(f"{what} file {path} is completely empty. Write at least the header row "
                          f"(for flags with no rows: as_of_week_start,store_id,issue_type_id,confidence,evidence_feedback_ids).")
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as e:  # noqa: BLE001
        raise FormatError(f"Could not read {what} {path} as CSV: {e}")


def need_cols(df: pd.DataFrame, cols, what: str, path: Path) -> None:
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise FormatError(f"{what} {path} is missing column(s) {missing}.\nRequired columns (exact names): {cols}\n"
                          f"Found: {list(df.columns)}")


def load_predictions(path: Path) -> pd.DataFrame:
    df = read_csv(path, "Predictions")
    need_cols(df, PRED_COLS, "Predictions", path)
    df = df[PRED_COLS].copy()
    for c in PRED_COLS:
        df[c] = df[c].astype(str).str.strip()
    if (df["feedback_id"] == "").any():
        raise FormatError(f"{int((df['feedback_id'] == '').sum())} row(s) have an empty feedback_id.")
    dup = df["feedback_id"][df["feedback_id"].duplicated()]
    if len(dup):
        raise FormatError(f"{dup.nunique()} feedback_id(s) appear more than once, e.g. {dup.unique()[:5].tolist()}. Keep exactly one row per feedback_id.")
    df["issue_type_id"] = df["issue_type_id"].str.upper()
    bad = df[~df["issue_type_id"].isin(ISSUE_TYPES)]
    if len(bad):
        raise FormatError(f"{len(bad)} row(s) have an invalid issue_type_id, e.g. {bad['issue_type_id'].unique()[:5].tolist()}.\n"
                          f"Allowed values: {ISSUE_TYPES} (see data/issue_taxonomy.csv).")
    df["severity"] = df["severity"].str.lower()
    bad = df[~df["severity"].isin(SEVERITIES)]
    if len(bad):
        raise FormatError(f"{len(bad)} row(s) have an invalid severity, e.g. {bad['severity'].unique()[:5].tolist()}. Allowed: {SEVERITIES}.")
    amap = {"0": 0, "1": 1, "0.0": 0, "1.0": 1, "true": 1, "false": 0}
    a = df["actionable"].str.lower().map(amap)
    if a.isna().any():
        raise FormatError(f"{int(a.isna().sum())} row(s) have an invalid actionable value, e.g. "
                          f"{df.loc[a.isna(), 'actionable'].unique()[:5].tolist()}. Use 0 or 1.")
    df["actionable"] = a.astype(int)
    return df


def load_flags(path: Path) -> pd.DataFrame:
    df = read_csv(path, "Emerging-flags")
    df.columns = [c.strip() for c in df.columns]
    if "evidence_feedback_ids" not in df.columns and all(c in df.columns for c in FLAG_COLS[:4]):
        raise FormatError(f"Emerging-flags {path} has no 'evidence_feedback_ids' column. Every flag must cite the feedback_ids it is based on, "
                          f"';'-separated (at least {EVIDENCE_MIN} from that store, that week, that you labelled with that issue type).")
    need_cols(df, FLAG_COLS, "Emerging-flags", path)
    df = df[FLAG_COLS].copy()
    for c in FLAG_COLS:
        df[c] = df[c].astype(str).str.strip()
    if len(df) == 0:
        return df.assign(confidence=pd.Series(dtype=float))
    df["store_id"] = df["store_id"].str.upper()
    bad = df[~df["as_of_week_start"].isin(WEEK_STARTS)]
    if len(bad):
        raise FormatError(f"{len(bad)} flag(s) have an invalid as_of_week_start, e.g. {bad['as_of_week_start'].unique()[:3].tolist()}.\n"
                          f"It must be the Monday (YYYY-MM-DD) of one of the 26 weeks: {WEEK_STARTS[0]} ... {WEEK_STARTS[-1]} "
                          f"(see data/week_calendar.csv).")
    if (df["store_id"] == "").any():
        raise FormatError("Some flags have an empty store_id. Every flag must name one store_id from data/store_master.csv.")
    df["issue_type_id"] = df["issue_type_id"].str.upper()
    bad = df[~df["issue_type_id"].isin(ISSUE_TYPES)]
    if len(bad):
        raise FormatError(f"{len(bad)} flag(s) have an invalid issue_type_id, e.g. {bad['issue_type_id'].unique()[:5].tolist()}.")
    conf = pd.to_numeric(df["confidence"], errors="coerce")
    if conf.isna().any() or (conf < 0).any() or (conf > 1).any():
        raise FormatError("confidence must be a number between 0 and 1 for every flag.")
    df["confidence"] = conf
    key = df[["as_of_week_start", "store_id", "issue_type_id"]].astype(str).agg("|".join, axis=1)
    if key.duplicated().any():
        raise FormatError(f"{int(key.duplicated().sum())} duplicate flag(s) (same as_of_week_start + store_id + issue_type_id), e.g. "
                          f"{key[key.duplicated()].iloc[0]}. Keep one row per (week, store, issue type).")
    return df


def load_truth(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FormatError(f"Truth file not found: {path}. For practice use --truth data/feedback_labels_train.csv")
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df["actionable"] = df["actionable"].astype(int)
    return df


def find_incidents(truth_path: Path) -> Path | None:
    d = truth_path.parent
    named = {"feedback_labels_train.csv": "emerging_incidents_train.csv", "test_truth.csv": "test_incidents.csv"}
    if truth_path.name in named and (d / named[truth_path.name]).exists():
        return d / named[truth_path.name]
    cands = sorted(d.glob("*incidents*.csv"))
    return cands[0] if len(cands) == 1 else None


class Evidence:
    """Facts from data/feedback.csv + store_master.csv used to check that a flag is grounded in that week's data."""

    def __init__(self, feedback_path: Path, stores_path: Path):
        for p in (feedback_path, stores_path):
            if not p.exists():
                raise FormatError(f"Needed for checking flag evidence but not found: {p}. Run evaluate.py from the package folder "
                                  f"or pass --feedback / --stores.")
        fb = pd.read_csv(feedback_path, dtype=str, keep_default_na=False, usecols=["feedback_id", "created_at", "store_id", "text"])
        sm = pd.read_csv(stores_path, dtype=str)
        self.store_ids = set(sm["store_id"].str.upper())
        # locality = store name without "Saffron <Format> ", e.g. "Saffron Market Kothrud" -> "kothrud"
        self.locality = {r.store_id.upper(): r.store_name.split(" ", 2)[2].lower() for r in sm.itertuples()}
        wk = (pd.to_datetime(fb["created_at"]).dt.normalize() - pd.Timestamp(PERIOD_START)).dt.days // 7 + 1
        self.week = dict(zip(fb["feedback_id"], wk))
        self.store = dict(zip(fb["feedback_id"], fb["store_id"].str.upper()))
        self.text = dict(zip(fb["feedback_id"], fb["text"].str.lower()))

    def belongs(self, fid: str, store: str) -> bool:
        s = self.store[fid]
        if s:
            return s == store
        loc = self.locality.get(store)
        return bool(loc) and loc in self.text[fid]


def check_evidence(fl: pd.DataFrame, pred_type: dict, ev: Evidence, widx: dict) -> tuple[np.ndarray, dict]:
    """A flag is VALID if it cites >= EVIDENCE_MIN distinct feedback_ids that (a) exist in feedback.csv, (b) belong to the flagged store
    (store_id equal, or store_id empty and the text names the store's locality), (c) were created in the flag's as_of week
    (Monday..Sunday) and (d) carry the flag's issue_type_id in YOUR R5_predictions.csv (organiser scoring of the hidden test checks (d)
    against the TRUE issue types instead, so relabelling a few rows cannot manufacture evidence)."""
    valid = np.zeros(len(fl), bool)
    reasons = {"too_few_ids": 0, "unknown_id": 0, "other_store": 0, "other_week": 0, "other_issue_type_in_your_predictions": 0}
    for i, r in enumerate(fl.itertuples(index=False)):
        ids = list(dict.fromkeys(x.strip().upper() for x in str(r.evidence_feedback_ids).replace(",", ";").split(";") if x.strip()))
        w = widx[r.as_of_week_start]
        good = 0
        for fid in ids:
            if fid not in ev.week:
                reasons["unknown_id"] += 1
            elif not ev.belongs(fid, r.store_id):
                reasons["other_store"] += 1
            elif ev.week[fid] != w:
                reasons["other_week"] += 1
            elif pred_type.get(fid) != r.issue_type_id:
                reasons["other_issue_type_in_your_predictions"] += 1
            else:
                good += 1
        if good >= EVIDENCE_MIN:
            valid[i] = True
        elif len(ids) < EVIDENCE_MIN:
            reasons["too_few_ids"] += 1
    return valid, reasons


# ------------------------------------------------------------------------------------------------ scoring
def score(pred: pd.DataFrame, truth: pd.DataFrame, flags: pd.DataFrame | None, incidents: pd.DataFrame | None,
          ev: "Evidence | None" = None, evidence_types: dict | None = None) -> dict:
    m = truth.merge(pred, on="feedback_id", how="left", suffixes=("", "_pred"))
    miss = m["issue_type_id_pred"].isna()
    n_missing = int(miss.sum())
    m.loc[miss, "issue_type_id_pred"] = MISSING
    m.loc[miss, "severity_pred"] = MISSING
    m.loc[miss, "actionable_pred"] = 1 - m.loc[miss, "actionable"]
    m["actionable_pred"] = m["actionable_pred"].astype(int)

    yt, yp = m["issue_type_id"].to_numpy(), m["issue_type_id_pred"].to_numpy()
    issue_f1 = macro_f1(yt, yp)
    sev_f1 = weighted_f1(m["severity"].to_numpy(), m["severity_pred"].to_numpy())
    act_f1 = binary_f1(m["actionable"].to_numpy(), m["actionable_pred"].to_numpy())
    classification = W_ISSUE_MACRO_F1 * issue_f1 + W_SEVERITY_WEIGHTED_F1 * sev_f1 + W_ACTIONABLE_F1 * act_f1

    esc = m["actionable_pred"] == 1
    act_prec = float(m.loc[esc, "actionable"].mean()) if esc.any() else 0.0
    esc_hi = esc & m["severity_pred"].isin(["high", "critical"])
    esc_prec = float(m.loc[esc_hi, "actionable"].mean()) if esc_hi.any() else 0.0
    hi_true = m["severity"].isin(["high", "critical"])
    hi_recall = float(m.loc[hi_true, "severity_pred"].isin(["high", "critical"]).mean()) if hi_true.any() else 0.0

    res = dict(
        n_scored=len(m), n_missing_predictions=n_missing, missing_examples=m.loc[miss, "feedback_id"].head(5).tolist(),
        issue_type_macro_f1=round(issue_f1, 6), severity_weighted_f1=round(sev_f1, 6), actionable_f1=round(act_f1, 6),
        classification_score=round(classification, 6),
        precision_statement=dict(
            escalated_records=int(esc.sum()), escalated_truly_actionable=round(act_prec, 4),
            escalated_high_or_critical=int(esc_hi.sum()), escalated_high_or_critical_truly_actionable=round(esc_prec, 4),
            recall_of_true_high_or_critical=round(hi_recall, 4)),
    )

    # ---- lead time
    per_inc = []
    widx = {w: i + 1 for i, w in enumerate(WEEK_STARTS)}
    fl = flags.copy() if flags is not None else pd.DataFrame(columns=FLAG_COLS)
    fl["w"] = fl["as_of_week_start"].map(widx)
    n_flags_total = len(fl)
    if incidents is not None and len(incidents):
        first = min(widx[w] for w in incidents["onset_week_start"])
        half = (1, HALF_WEEKS) if first <= HALF_WEEKS else (HALF_WEEKS + 1, N_WEEKS)
        fl = fl[(fl["w"] >= half[0]) & (fl["w"] <= half[1])].reset_index(drop=True)
    else:
        half = (1, N_WEEKS)
    n_flags = len(fl)
    avg_fpw = n_flags / (half[1] - half[0] + 1)
    flood = min(1.0, FLAG_BUDGET_PER_WEEK / avg_fpw) if avg_fpw > 0 else 1.0   # every submitted flag in the half uses budget
    if ev is not None and n_flags:
        types_for_evidence = evidence_types if evidence_types is not None else dict(zip(pred["feedback_id"], pred["issue_type_id"]))
        valid, reasons = check_evidence(fl, types_for_evidence, ev, widx)
        unknown_store = int((~fl["store_id"].isin(ev.store_ids)).sum())
    else:
        valid, reasons, unknown_store = np.zeros(n_flags, bool) if ev is None else np.ones(n_flags, bool), {}, 0
    matched_flags = 0
    if incidents is not None and len(incidents):
        flag_hit = np.zeros(len(fl), bool)
        for inc in incidents.itertuples():
            stores = str(inc.store_ids).split(";")
            firsts = str(getattr(inc, "store_first_week_starts", "")).split(";")
            first_w = {s_: widx.get(f_, widx[inc.onset_week_start]) for s_, f_ in zip(stores, firsts + [""] * len(stores))}
            onset, naive = widx[inc.onset_week_start], widx[inc.naive_detect_week_start]
            last = widx.get(getattr(inc, "last_week_start", ""), naive + 4)
            joined = np.array([s_ in first_w and w_ >= first_w[s_] for s_, w_ in zip(fl["store_id"], fl["w"])], bool)
            ok = joined & (fl["issue_type_id"] == inc.issue_type_id).to_numpy() & valid
            hits = fl.loc[ok & (fl["w"] >= onset).to_numpy(), "w"]
            team = int(hits.min()) if len(hits) else None
            lead = LEAD_MIN if team is None else int(np.clip(naive - team, LEAD_MIN, LEAD_MAX))
            per_inc.append(dict(incident_id=inc.incident_id, issue_type_id=inc.issue_type_id, onset_week_start=inc.onset_week_start,
                                naive_detect_week_start=inc.naive_detect_week_start,
                                your_first_matching_flag=WEEK_STARTS[team - 1] if team else None, lead_weeks=lead,
                                incident_score=round((lead - LEAD_MIN) / (LEAD_MAX - LEAD_MIN), 6)))
            flag_hit |= ok & (fl["w"] >= onset).to_numpy() & (fl["w"] <= last + 2).to_numpy()
        matched_flags = int(flag_hit.sum())
        lead_raw = float(np.mean([p["incident_score"] for p in per_inc]))
    else:
        lead_raw = 0.0
    lead_score = lead_raw * flood
    res.update(
        scored_weeks=f"{WEEK_STARTS[half[0] - 1]}..{WEEK_STARTS[half[1] - 1]}", n_flags_total=n_flags_total,
        n_flags=n_flags, n_flags_valid=int(valid.sum()), n_flags_rejected=int(n_flags - valid.sum()), rejection_reasons=reasons,
        flags_unknown_store=unknown_store, avg_flags_per_week=round(avg_fpw, 4), flood_factor=round(flood, 6), lead_score_raw=round(lead_raw, 6),
        lead_score=round(lead_score, 6), flag_precision=round(matched_flags / n_flags, 4) if n_flags else None, incidents=per_inc,
    )
    res["primary_score"] = round(W_CLASSIFICATION * classification + W_LEAD * lead_score, 6)
    res["formula"] = ("primary = 0.6*classification + 0.4*lead_score; classification = 0.5*macroF1(issue_type) + 0.25*weightedF1(severity) "
                      "+ 0.25*F1(actionable); lead_score = mean_i((clip(naive_i - team_i, -2, 4) + 2) / 6) * min(1, 3 / flags_per_week); "
                      "flags_per_week = flags inside the scored 13-week half / 13")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="R5 Voice-of-Store Engine scorer")
    ap.add_argument("--submission", required=True, help="path to R5_predictions.csv (or the folder that contains it)")
    ap.add_argument("--truth", required=True, help="path to the labels file (data/feedback_labels_train.csv for practice)")
    ap.add_argument("--flags", default=None, help="path to R5_emerging_flags.csv (default: next to the predictions)")
    ap.add_argument("--incidents", default=None, help="incident key (default: found next to the truth file)")
    ap.add_argument("--feedback", default=str(HERE / "data" / "feedback.csv"))
    ap.add_argument("--stores", default=str(HERE / "data" / "store_master.csv"))
    ap.add_argument("--out", default="score.json")
    a = ap.parse_args()

    sub = Path(a.submission)
    if sub.is_dir():
        sub = sub / "R5_predictions.csv"
    try:
        pred = load_predictions(sub)
        flags_path = Path(a.flags) if a.flags else sub.parent / "R5_emerging_flags.csv"
        flags = None
        if flags_path.exists():
            flags = load_flags(flags_path)
        else:
            print(f"WARNING: no emerging-flags file at {flags_path} -> every incident counts as undetected (lead score 0).")
        truth = load_truth(Path(a.truth))
        inc_path = Path(a.incidents) if a.incidents else find_incidents(Path(a.truth))
        if inc_path is None or not inc_path.exists():
            raise FormatError(f"No incident key found for truth file {a.truth} (expected emerging_incidents_train.csv / test_incidents.csv next to it, "
                              f"or pass --incidents).")
        incidents = pd.read_csv(inc_path, dtype=str)
        ev = Evidence(Path(a.feedback), Path(a.stores))
        out_path = Path(a.out)
        if not out_path.parent.exists():
            raise FormatError(f"Cannot write --out {out_path}: folder {out_path.parent} does not exist.")
    except FormatError as e:
        fail(str(e))
        return

    latent = Path(a.truth).parent / "all_records_latent.csv"     # present only in the organisers' hidden folder
    evidence_types = None
    if latent.exists():
        lt = pd.read_csv(latent, usecols=["feedback_id", "issue_type_id"], dtype=str)
        evidence_types = dict(zip(lt["feedback_id"], lt["issue_type_id"]))
        print("Organiser mode: flag evidence rule (d) is checked against the TRUE issue types.")
    r = score(pred, truth, flags, incidents, ev, evidence_types)

    print("=" * 78)
    print("R5 Voice-of-Store Engine — score")
    print("=" * 78)
    if r["n_missing_predictions"]:
        print(f"!!! {r['n_missing_predictions']} of {r['n_scored']} scored feedback_ids have NO prediction (scored as wrong), "
              f"e.g. {r['missing_examples']}")
    print(f"Scored records                      : {r['n_scored']}")
    print(f"Issue type macro-F1      (x0.50)    : {r['issue_type_macro_f1']:.4f}")
    print(f"Severity weighted-F1     (x0.25)    : {r['severity_weighted_f1']:.4f}")
    print(f"Actionable F1            (x0.25)    : {r['actionable_f1']:.4f}")
    print(f"CLASSIFICATION SCORE                : {r['classification_score']:.4f}")
    print("-" * 78)
    for p in r["incidents"]:
        print(f"Incident {p['incident_id']:<6} {p['issue_type_id']}  onset {p['onset_week_start']}  naive {p['naive_detect_week_start']}  "
              f"your flag {p['your_first_matching_flag']}  lead {p['lead_weeks']:+d} wk  -> {p['incident_score']:.3f}")
    print(f"Flags scored in weeks {r['scored_weeks']}: {r['n_flags']} (of {r['n_flags_total']} in file), {r['avg_flags_per_week']:.2f}/week, "
          f"flood factor {r['flood_factor']:.3f}, flag precision {r['flag_precision']}")
    if r["n_flags"]:
        print(f"Flag evidence check: {r['n_flags_valid']} valid, {r['n_flags_rejected']} rejected (not counted). Evidence-id problems: {r['rejection_reasons']}")
    if r["flags_unknown_store"]:
        print(f"WARNING: {r['flags_unknown_store']} flag(s) name a store_id that is not in data/store_master.csv.")
    print(f"LEAD SCORE (raw {r['lead_score_raw']:.4f} x flood)  : {r['lead_score']:.4f}")
    print("-" * 78)
    ps = r["precision_statement"]
    print(f"Precision statement: of {ps['escalated_records']} records you marked actionable, {ps['escalated_truly_actionable']:.1%} truly were; "
          f"of {ps['escalated_high_or_critical']} you marked actionable AND high/critical, {ps['escalated_high_or_critical_truly_actionable']:.1%} were truly actionable.")
    print("=" * 78)
    print(f"PRIMARY SCORE (0..1, higher is better): {r['primary_score']:.4f}")
    print("=" * 78)
    Path(a.out).write_text(json.dumps(r, indent=2), encoding="utf-8")
    print(f"(details written to {a.out})")


if __name__ == "__main__":
    main()
