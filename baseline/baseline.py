#!/usr/bin/env python3
"""R5 baseline — deliberately simple and honest.

1. Classification: hand-written multilingual keyword rules per issue type (first match wins), severity = the
   taxonomy's policy floor (+ a few "critical" words), actionable = "is an issue and the text is not tiny".
2. Emerging-issue flags: weekly counts per (store, predicted issue type); flag when this week's count is >= 3 and
   its z-score against that store's previous 8 weeks is >= 3; keep at most 3 flags per week. Uses only data up to
   each week's Sunday (causal / as-of). Each flag cites the feedback_ids it counted as evidence.

Run from the package folder:   python baseline/baseline.py
Writes submission/R5_predictions.csv and submission/R5_emerging_flags.csv (predictions for ALL rows).

Re-run interface (required from every team, see README "Re-run detector"):
    python baseline/baseline.py --feedback <feedback.csv> --as-of YYYY-MM-DD --out <flags.csv>
writes only that week's flags, using only rows with created_at <= that week's Sunday 23:59:59.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "submission"

# (issue_type_id, regex) — checked in this order, first match wins. English + Hinglish + Tamil + Marathi cues.
RULES = [
    ("NI03", r"click|subscribe|telegram|crypto|loan|earn \d+|kamao|sambaadhi|kamva|youtube|instagram for"),
    ("IT18", r"allerg|ingredient|label|declare|veg dot"),
    ("IT17", r"worm|insect|keed|puzhu|kide|stone|pathar|dagad|glass piece|kaanch|glass thundu|hair|mudi|metal pin"),
    ("IT04", r"abus|gaali|shivya|thitt|harass|shout|chilla|kathi|orad|misbehav|badtameez|uddhat|chor\b|thief|thirudan|push|dhakka|thalli"),
    ("IT10", r"freez|frzr|chiller|melt|pighal|urugi|vitalun|thaw|not cold|cooling"),
    ("IT06", r"cockroach|karappan|jhur|\brats?\b|chuh|undir|\beli\b|flies|makkhi|mashya|pest|filthy|unhygien|hygiene|washroom|badbu|naatram|ghaan"),
    ("IT08", r"slip|fisal|vazhuk|ghasar|wire|shock|current|fire exit|wet floor|geela|caution"),
    ("IT09", r"leak|tapak|ozhug|galt|seepage|seelan|ceiling|chhat|roof|drip"),
    ("IT16", r"expir|use-by|fefo"),
    ("IT27", r"debit|deduct|kat gaye|cut aay|katle|upi|payment fail|charged twice"),
    ("IT28", r"refund"),
    ("IT29", r"points|coupon|rewards"),
    ("IT26", r"\bapp\b|otp|website|login|logout|crash"),
    ("IT24", r"missing|wrong item|galat saman|thappana porul|chukicha saaman|substitut|different brand|instead of"),
    ("IT25", r"broken|damag|toot|udanj|futl|crushed|leaked|leaking"),
    ("IT23", r"deliver|slot"),
    ("IT19", r"shelf tag|price tag|shelf price|tag "),
    ("IT20", r"offer|bogo|buy 1|% off|combo|promo|discount"),
    ("IT30", r"scan|twice|double|do baar|rendu dhadava|don vela|wazan|vajan|weight"),
    ("IT12", r"carry bag|paper bag|packing"),
    ("IT13", r"parking|ramp|closed|band kar|opened late|timing"),
    ("IT11", r"\bac\b|lift|escalator|weighing|card machine|lights?\b|printer"),
    ("IT14", r"out of stock|oos|empty|khaali|kaali|rikam|not available|khatam|theern|sampla|restock"),
    ("IT15", r"rotten|stale|sade|azhugi|sadle|baasi|shila|black spot|vegetable|sabzi|bhaji|kaaikari"),
    ("IT21", r"saffron select|saffron kitchen"),
    ("IT22", r"please keep|rakho|vechu kudunga|theva|range|variety"),
    ("IT05", r"salary|sambalam|pagar|weekly off|incentive|uniform"),
    ("IT02", r"absent|understaff|short of staff|no staff|nobody|koi nahi|yaarum illa|konich"),
    ("IT01", r"queue|line|billing|counter|\bq\b|rang\b"),
    ("IT07", r"carton|mess|bikhr|kalanju|pasara|trolley|godown"),
    ("IT03", r"staff|attitude|ignore|shrug"),
    ("NI01", r"good|great|nice|love|best|thank|accha|nalla|chhan|happy|fresh|excellent"),
]
RULES = [(t, re.compile(p, re.I)) for t, p in RULES]
CRITICAL_WORDS = re.compile(r"hospital|sick|poisoning|injur|stitch|doctor|reaction|rashes|beemar|vaanthi|aajari|harass", re.I)
NON_ISSUE = {"NI01", "NI02", "NI03"}


def classify(text: str) -> str:
    for t, rx in RULES:
        if rx.search(text):
            return t
    return "NI02"


def label(fb: pd.DataFrame, tax: pd.DataFrame) -> pd.DataFrame:
    text = fb["text"].fillna("").astype(str)
    fb = fb.copy()
    fb["issue_type_id"] = text.map(classify)
    floor = fb["issue_type_id"].map(tax["policy_severity_floor"])
    sev = np.where(floor == "high", "high", "medium")
    sev = np.where(fb["issue_type_id"].isin(NON_ISSUE), "low", sev)
    sev = np.where(text.str.contains(CRITICAL_WORDS) & (floor == "high"), "critical", sev)
    fb["severity"] = sev
    fb["actionable"] = ((~fb["issue_type_id"].isin(NON_ISSUE)) & (text.str.len() > 40)).astype(int)
    return fb


def emerging_flags(fb: pd.DataFrame, weeks: list[str], emit: list[str], names: dict | None = None) -> pd.DataFrame:
    """Rolling z-score per (store, predicted issue type). The flag for week w uses only weeks <= w (causal)."""
    fb = fb.copy()
    fb["week_start"] = pd.to_datetime(fb["created_at"]).dt.to_period("W-SUN").dt.start_time.dt.strftime("%Y-%m-%d")
    issues = fb[(~fb["issue_type_id"].isin(NON_ISSUE)) & fb["store_id"].notna()]
    counts = issues.groupby(["store_id", "issue_type_id", "week_start"]).size().unstack(fill_value=0).reindex(columns=weeks, fill_value=0)
    evidence = issues.groupby(["store_id", "issue_type_id", "week_start"])["feedback_id"].apply(lambda s: ";".join(sorted(s)))
    flags = []
    for i, w in enumerate(weeks):
        if i < 4 or w not in emit:
            continue
        hist = counts.iloc[:, max(0, i - 8): i]
        cur = counts.iloc[:, i]
        mu, sd = hist.mean(axis=1), hist.std(axis=1, ddof=0).clip(lower=1.0)
        z = (cur - mu) / sd
        cand = z[(cur >= 3) & (z >= 3)].reset_index()
        cand.columns = ["store_id", "issue_type_id", "z"]
        cand["name"] = cand["store_id"].map(names or {}).fillna(cand["store_id"])   # ties broken by store name, not by id
        cand = cand.sort_values(["z", "name", "issue_type_id"], ascending=[False, True, True], kind="mergesort").head(3)
        for r in cand.itertuples():
            flags.append(dict(as_of_week_start=w, store_id=r.store_id, issue_type_id=r.issue_type_id, confidence=round(min(1.0, r.z / 10), 3),
                              evidence_feedback_ids=evidence.loc[(r.store_id, r.issue_type_id, w)]))
    return pd.DataFrame(flags, columns=["as_of_week_start", "store_id", "issue_type_id", "confidence", "evidence_feedback_ids"])


def main() -> None:
    ap = argparse.ArgumentParser(description="R5 baseline. No arguments: full submission. With --as-of: one week's flags (re-run interface).")
    ap.add_argument("--feedback", default=str(DATA / "feedback.csv"), help="feedback file (possibly truncated by the organisers)")
    ap.add_argument("--as-of", dest="as_of", default=None, help="YYYY-MM-DD; any day of the week to flag (normalised to its Monday)")
    ap.add_argument("--out", default=None, help="flags file to write in --as-of mode")
    a = ap.parse_args()

    fb = pd.read_csv(a.feedback, dtype={"store_id": str})
    # Reference files are read from the folder of --feedback (the organisers' re-run gives a disguised copy of the whole data
    # folder: shifted dates, new feedback/store ids). Never hard-code dates or ids.
    src = Path(a.feedback).resolve().parent
    ref = lambda name: src / name if (src / name).exists() else DATA / name  # noqa: E731
    tax = pd.read_csv(ref("issue_taxonomy.csv")).set_index("issue_type_id")
    weeks = pd.read_csv(ref("week_calendar.csv"))["week_start"].tolist()
    sm = pd.read_csv(ref("store_master.csv"))
    names = dict(zip(sm["store_id"], sm["store_name"]))

    if a.as_of:
        monday = (pd.Timestamp(a.as_of) - pd.Timedelta(days=pd.Timestamp(a.as_of).weekday())).normalize()
        cutoff = monday + pd.Timedelta(days=7)               # strictly before next Monday 00:00 = Sunday 23:59:59
        fb = fb[pd.to_datetime(fb["created_at"]) < cutoff]   # never look past the as-of Sunday, whatever file we are given
        fl = emerging_flags(label(fb, tax), weeks, emit=[monday.strftime("%Y-%m-%d")], names=names)
        out = Path(a.out or "R5_emerging_flags_asof.csv")
        fl.to_csv(out, index=False)
        print(f"as-of {monday.date()}: wrote {out} ({len(fl)} flags, {len(fb)} rows used)")
        return

    fb = label(fb, tax)
    OUT.mkdir(exist_ok=True)
    fb[["feedback_id", "issue_type_id", "severity", "actionable"]].to_csv(OUT / "R5_predictions.csv", index=False)
    fl = emerging_flags(fb, weeks, emit=weeks, names=names)
    fl.to_csv(OUT / "R5_emerging_flags.csv", index=False)
    (OUT / "detector_cmd.txt").write_text("python baseline/baseline.py --feedback {feedback} --as-of {asof} --out {out}\n", encoding="utf-8")
    print(f"wrote {OUT / 'R5_predictions.csv'} ({len(fb)} rows) and {OUT / 'R5_emerging_flags.csv'} ({len(fl)} flags)")


if __name__ == "__main__":
    main()
