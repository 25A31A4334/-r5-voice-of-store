"""Unit Tests for Phase 3 Edge Cases (Team CodeNova).

Author: Team CodeNova
Usage:
    python FULL_CODE/test_phase3_edge_cases.py
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd

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
from FULL_CODE.severity_engine import SeverityEngine
from FULL_CODE.actionability_engine import ActionabilityEngine


def run_edge_case_tests() -> None:
    print("=" * 70)
    print("TESTING PHASE 3 EDGE CASES")
    print("=" * 70)

    resolver = LocalityResolver()
    sev_engine = SeverityEngine()
    act_engine = ActionabilityEngine()

    # Fit engines on labelled training data for accurate realistic inference
    train_df = pd.read_csv(ROOT / "data" / "feedback_labels_train.csv")
    fb_df = pd.read_csv(ROOT / "data" / "feedback.csv")
    full_train = train_df.merge(fb_df, on="feedback_id")

    sev_engine.fit(full_train["text"], full_train["severity"])
    act_engine.fit(full_train["text"], full_train["actionable"])

    passed = 0
    total = 0

    def assert_test(name: str, condition: bool, details: str = "") -> None:
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f"  [PASS] {name} {details}")
        else:
            print(f"  [FAIL] {name} {details}")

    # -------------------------------------------------------------
    # 1. Non-Issues Edge Cases (NI01, NI02, NI03)
    # -------------------------------------------------------------
    print("\n--- 1. Non-Issues Edge Cases ---")

    # Praise (NI01)
    praise_txt = "Great service today, staff at Kankarbagh were very helpful and polite!"
    praise_sev = sev_engine.predict_single(praise_txt, "NI01")
    praise_act = act_engine.predict_single(praise_txt, "ST-D69EG", "NI01")
    assert_test("NI01 Praise Severity is Low", praise_sev == "low", f"got {praise_sev}")
    assert_test("NI01 Praise Actionable is 0", praise_act == 0, f"got {praise_act}")

    # General Chatter / Suggestion (NI02)
    chatter_txt = "Can you please open a new store near our residential area?"
    chatter_sev = sev_engine.predict_single(chatter_txt, "NI02")
    chatter_act = act_engine.predict_single(chatter_txt, None, "NI02")
    assert_test("NI02 Chatter Severity is Low", chatter_sev == "low", f"got {chatter_sev}")
    assert_test("NI02 Chatter Actionable is 0", chatter_act == 0, f"got {chatter_act}")

    # Spam (NI03)
    spam_txt = "Earn 50000 per day join telegram channel t.me/crypto now"
    spam_sev = sev_engine.predict_single(spam_txt, "NI03")
    spam_act = act_engine.predict_single(spam_txt, None, "NI03")
    assert_test("NI03 Spam Severity is Low", spam_sev == "low", f"got {spam_sev}")
    assert_test("NI03 Spam Actionable is 0", spam_act == 0, f"got {spam_act}")

    # -------------------------------------------------------------
    # 2. Missing Store IDs & Routability Edge Cases
    # -------------------------------------------------------------
    print("\n--- 2. Missing Store IDs & Routability ---")

    # In-store issue with NO store_id and NO locality -> cannot route -> actionable=0
    unroutable_txt = "Waited 45 mins at billing counter, only 1 cashier active."
    act_unroutable = act_engine.predict_single(unroutable_txt, None, "IT01")
    assert_test("In-store issue without store_id or locality is NOT actionable", act_unroutable == 0, f"got {act_unroutable}")

    # In-store issue with NO store_id, BUT locality mentioned -> resolved -> actionable=1
    loc_txt = "Waited 45 mins at billing counter in Kankarbagh, only 1 cashier active."
    resolved_sid, _, _ = resolver.resolve_text(loc_txt)
    act_loc = act_engine.predict_single(loc_txt, resolved_sid, "IT01")
    assert_test("In-store issue with locality resolved to store IS routable and actionable",
                act_loc == 1 and resolved_sid == "ST-D69EG", f"store={resolved_sid}, act={act_loc}")

    # Digital issue (IT26) with NO store_id -> digital doesn't need store -> actionable=1
    app_txt = "App crashed on Android while paying Rs 450 during OTP verification."
    act_digital = act_engine.predict_single(app_txt, None, "IT26")
    assert_test("Digital issue (IT26) without store_id IS routable and actionable", act_digital == 1, f"got {act_digital}")

    # Delivery issue (IT23) with NO store_id -> delivery doesn't need store -> actionable=1
    deliv_txt = "Morning slot delivery was missed, arrived 4 hours late with melted butter."
    act_deliv = act_engine.predict_single(deliv_txt, None, "IT23")
    assert_test("Delivery issue (IT23) without store_id IS routable and actionable", act_deliv == 1, f"got {act_deliv}")

    # -------------------------------------------------------------
    # 3. High/Critical Safety & Policy Floors
    # -------------------------------------------------------------
    print("\n--- 3. High/Critical Policy Floors & Critical Triggers ---")

    # Food safety / Cold-chain failure (IT10) -> floor is high
    cold_txt = "The ice cream in the freezer was completely thawed and melting."
    cold_sev = sev_engine.predict_single(cold_txt, "IT10")
    assert_test("IT10 Cold-chain floor is High", cold_sev in ["high", "critical"], f"got {cold_sev}")

    # Allergen labelling error with Hospitalization (IT18) -> critical harm
    allergen_crit_txt = "Egg was found in eggless cake, child had severe allergic reaction and was admitted to hospital emergency!"
    allergen_sev = sev_engine.predict_single(allergen_crit_txt, "IT18")
    assert_test("IT18 Allergen issue with hospital reaction is CRITICAL", allergen_sev == "critical", f"got {allergen_sev}")

    # Physical safety hazard (IT08) -> floor is high
    hazard_txt = "Exposed live electrical wire hanging loose near billing counter 3."
    hazard_sev = sev_engine.predict_single(hazard_txt, "IT08")
    assert_test("IT08 Physical safety hazard floor is High", hazard_sev in ["high", "critical"], f"got {hazard_sev}")

    # Staff misconduct (IT04) -> floor is high
    misconduct_txt = "Security guard shouted abusive slurs and grabbed customer by the arm."
    misconduct_sev = sev_engine.predict_single(misconduct_txt, "IT04")
    assert_test("IT04 Staff misconduct floor is High", misconduct_sev in ["high", "critical"], f"got {misconduct_sev}")

    # -------------------------------------------------------------
    # 4. Low Severity Floor Issues
    # -------------------------------------------------------------
    print("\n--- 4. Low Severity Floor Issues (Verifying 'low' prediction works) ---")

    # Minor shelf tag issue (IT19) -> can be low
    minor_tag_txt = "Shelf price said 45 but billed 48, small difference."
    minor_sev = sev_engine.predict_single(minor_tag_txt, "IT19")
    assert_test("IT19 minor issue predicts LOW (fixing baseline bug)", minor_sev == "low", f"got {minor_sev}")

    print("\n" + "=" * 70)
    print(f"EDGE CASE SUMMARY: {passed}/{total} TESTS PASSED ({(passed/total)*100:.1f}%)")
    print("=" * 70)


if __name__ == "__main__":
    run_edge_case_tests()
