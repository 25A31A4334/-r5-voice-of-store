# R5 — Turning Store Chatter Into Action: The Voice-of-Store Engine

**Saffron Retail Group** is a fictional Indian grocery and general-merchandise chain.
It has 60 stores in three formats: large *Saffron Hyper*, mid-size *Saffron Market* and small *Saffron Express*.
The stores are spread across five regions. There is also an app and a website (saffronretail.example).

Head office is drowning in unstructured feedback: online reviews, in-app ratings, store-staff shift notes and call-centre transcripts.
Real operational problems (a broken freezer in one store, a mislabelled allergen, a rude billing counter) are buried in the noise.
They surface weeks late, if ever.

**Your job:** turn this messy, multi-source, multilingual feedback stream into a **prioritised weekly action list routed to the
right owner**. Concretely, you must deliver:

1. **A weekly one-page brief per region:** top 5 issues, evidence quotes, affected stores, and a trend arrow vs last week.
2. **Routing:** every issue tagged with its owning function and a severity, with your escalation rule stated.
3. **Emerging-issue detection:** flag an issue that is small in absolute volume but rising sharply at one store, *before* it
   becomes a national problem.
4. **A score from `evaluate.py`.**
5. **A precision statement:** of the issues you escalated, what fraction were truly actionable.

Stretch goal: de-duplicate the same incident reported through several channels, so it appears once.

> **In short**
>
> - **You get:** 39,769 feedback records from 60 stores over 26 weeks, in `data/feedback.csv`. Labels are given for a sample of 3,000 records from weeks 1–13.
> - **You build:** (a) a classifier that gives every record an issue type, a severity and an actionable flag (0/1); (b) a weekly emerging-issue detector; (c) the regional brief and routing described above.
> - **You submit:** `teamID_R5.zip` → `submission/R5_predictions.csv`, `submission/R5_emerging_flags.csv` and `submission/detector_cmd.txt`, plus all your code and a `README.md` (see **What to submit**).
> - **You are scored by:** `primary_score = 0.6 × classification + 0.4 × lead_score` (0 to 1, higher is better). Lead score rewards catching 3 hidden incidents earlier than a naive detector.
> - **Special rules:** a flag only counts if it cites at least 2 pieces of evidence from that store, that week and that issue type. Each week's flags must use only feedback up to that week's Sunday (no "future" data). The organisers check this from your outputs and code, and may ask you to run your detector on a disguised copy of the data in front of the jury.

## Synthetic data notice
Everything here is synthetic, generated for the TalentAP Mega Hackathon 2026. Stores, people, products and brands are fictional
(the cities, states and neighbourhood names are real places). Phone numbers, order numbers and similar identifiers inside the
texts are redacted. No real customer data is used.

## What's in the box

| File | Rows | Description |
|---|---|---|
| `data/feedback.csv` | 39,769 | The feedback stream, 2026-03-30 to 2026-09-27 (26 Monday–Sunday weeks). 9,602 online reviews, 13,340 in-app comments, 8,347 staff shift notes, 8,480 call-centre transcripts. ~8.0 MB. |
| `data/feedback_labels_train.csv` | 3,000 | Labels (issue type, severity, actionable) for a sample of records from weeks 1–13. |
| `data/emerging_incidents_train.csv` | 1 | A **worked example** of an emerging incident in the labelled period, in exactly the format used to score emerging-issue detection. |
| `data/issue_taxonomy.csv` | 33 | 30 operational issue types (IT01–IT30) with owning function and policy severity floor, plus 3 non-issue categories (NI01–NI03). |
| `data/store_master.csv` | 60 | Store id, name, city, state, region, format, size, average weekly footfall, opening date. |
| `data/week_calendar.csv` | 26 | Week index, Monday start, Sunday end, and whether labels for that week are public (train) or hidden (test). |
| `sample_submission/` | | A valid (but deliberately useless) submission in the exact format: `R5_predictions.csv` + `R5_emerging_flags.csv` + `detector_cmd.txt`. |
| `evaluate.py` | | The official scorer (the organisers run the same file on the hidden labels). |
| `baseline/baseline.py` | | A simple baseline that writes a valid submission. It uses keyword rules and a rolling z-score (how many standard deviations this week's count is above the recent weekly average). |

## Data dictionary

**`data/feedback.csv`**

| Column | Type | Description | Example | Can be missing? |
|---|---|---|---|---|
| `feedback_id` | string | Unique random id (carries no meaning) | `FB-7K2Q9XLM` | No |
| `channel` | string | `online_review`, `in_app`, `staff_shift_note`, `call_centre_ticket` | `in_app` | No |
| `created_at` | timestamp | Local time (IST), `YYYY-MM-DDTHH:MM:SS` | `2026-07-14T19:42:10` | No |
| `store_id` | string | Store the feedback is about, when the channel recorded it. Online reviews, app comments and some tickets often do not — the text may still name the store | `ST-4H2KQ` | Yes |
| `rating` | integer 1–5 | Star rating (online reviews and in-app only) | `2` | Yes (always empty for staff notes and call-centre; occasionally empty for reviews) |
| `text` | string | Free text: English, Hinglish (Hindi mixed with English), transliterated Tamil or transliterated Marathi (written in English letters). All texts are in Latin script. Texts have typos, emojis, abbreviations and truncation (some texts are very short). Call-centre transcripts look like `Agent: … Customer: …` | `milk over by 9am again, need higher indent` | No |

**`data/feedback_labels_train.csv`** (same schema as the hidden test labels)

| Column | Type | Description | Example |
|---|---|---|---|
| `feedback_id` | string | Joins to `feedback.csv` | `FB-7K2Q9XLM` |
| `issue_type_id` | string | One of IT01–IT30, NI01–NI03 (see taxonomy) | `IT14` |
| `severity` | string | `low`, `medium`, `high`, `critical` | `medium` |
| `actionable` | 0/1 | 1 = a concrete operational problem the owning function can act on (see below) | `1` |

**`data/emerging_incidents_train.csv`** (same schema as the hidden incident key)

| Column | Description |
|---|---|
| `incident_id` | Incident name |
| `store_ids` | Store(s) affected, `;`-separated |
| `store_first_week_starts` | For each store in `store_ids` (same order), the Monday of the first week the incident reached that store |
| `issue_type_id` | The incident's issue type |
| `onset_week_start` | Monday of the week the incident started |
| `naive_detect_week_start` | Monday of the week a naive raw-count detector would first catch it (definition in "How you're scored") |
| `last_week_start` | Monday of the last week the incident produced feedback |

**`data/issue_taxonomy.csv`** (the list of issue categories). Columns: `issue_type_id`, `issue_type`, `description`,
`owner_function` (Store Ops, Supply Chain, Merchandising, Digital, HR; non-issues say "None (not actionable)"),
`policy_severity_floor`, `policy_reason`, `is_actionable_category` (0 for NI01–NI03), `examples`.

| id | issue type | owner | policy floor |
|---|---|---|---|
| IT01 | Long checkout queue / slow billing | Store Ops | low |
| IT02 | Understaffing / staff shortage on floor | HR | low |
| IT03 | Unhelpful or poorly trained staff | HR | low |
| IT04 | Staff misconduct (abusive, harassment, cheating customers) | HR | high |
| IT05 | Staff welfare grievance | HR | low |
| IT06 | Hygiene lapse (pests, dirty food areas, foul smell) | Store Ops | high |
| IT07 | Store untidy / poor upkeep | Store Ops | low |
| IT08 | Physical safety hazard (wet floor, wiring, falling stock) | Store Ops | high |
| IT09 | Roof leak / water seepage | Store Ops | low |
| IT10 | Refrigeration / cold-chain failure | Store Ops | high |
| IT11 | Equipment breakdown (AC, lift, lights, scale, POS) | Store Ops | low |
| IT12 | Carry-bag charge / checkout packing | Store Ops | low |
| IT13 | Parking, access or store timings | Store Ops | low |
| IT14 | Out of stock / empty shelves | Supply Chain | low |
| IT15 | Poor quality fresh produce | Supply Chain | low |
| IT16 | Expired / near-expiry product on shelf | Store Ops | high |
| IT17 | Foreign object / contamination in product | Merchandising | high |
| IT18 | Allergen / ingredient labelling error | Merchandising | high |
| IT19 | Shelf price vs bill price mismatch | Merchandising | low |
| IT20 | Promotion / offer not applied | Merchandising | low |
| IT21 | Private-label product quality | Merchandising | low |
| IT22 | Assortment request / product not carried | Merchandising | low |
| IT23 | Online order delivery delay / missed slot | Supply Chain | low |
| IT24 | Wrong or missing items in online order | Supply Chain | low |
| IT25 | Damaged or leaking items on delivery | Supply Chain | low |
| IT26 | App / website crash, login or bug | Digital | low |
| IT27 | Payment failure / money debited but order failed | Digital | medium |
| IT28 | Refund / return not processed | Digital | low |
| IT29 | Loyalty points / coupon problem | Digital | low |
| IT30 | Billing error at counter (double scan, wrong weight/qty) | Store Ops | low |
| NI01 | Praise / compliment | None (not actionable) | low |
| NI02 | General comment / suggestion / question | None (not actionable) | low |
| NI03 | Spam / irrelevant | None (not actionable) | low |

**`data/store_master.csv`**: `store_id`, `store_name`, `city`, `state`, `region` (North, West, South, East, Central), `format`,
`size_sqft`, `avg_weekly_footfall`, `opened_date`.

**`data/week_calendar.csv`**: `week_index` (1–26), `week_start` (Monday), `week_end` (Sunday), `labelled_period` (`train` = weeks 1–13, `test` = weeks 14–26).

### How the labels were assigned (annotation guideline)

* **Issue type**: the single best-matching category.
    * Second-hand chatter about something the writer did not experience is NI02.
    * Routine staff notes, questions and suggestions are also NI02.
    * Adverts and gibberish are NI03.
* **Severity**: `max(policy floor, impact)`. In words: take the higher of the policy floor and the impact.
    * By policy, anything about **safety, allergens, food safety, hygiene or staff misconduct is at least `high`, regardless of
      volume**. The floors are in the taxonomy.
    * `critical` = actual harm or imminent danger: injury, illness or hospital visit, an allergic reaction or an allergen that is
      present but not declared on the label, assault or harassment.
    * Otherwise impact is judged from the text: a minor note → `low`; repeated or costly → `medium`/`high`.
    * Some texts give few clues, so severity is the hardest label.
    * Failed payments (IT27) are at least `medium`, because the customer's money is held.
* **Actionable = 1** when all three of these hold:
    1. It is a real issue (IT01–IT30, not praise/chatter/spam).
    2. It is **specific**: it has what/where/when details, rather than a generic rant such as "worst store ever".
    3. It can be **routed**: the store is known (from `store_id` or named in the text), or it is an
       order/app/payment/refund/loyalty issue (IT23–IT29) that does not need a store.

## Know your data

* Text is deliberately messy and code-mixed (several languages mixed in one text). There are four language varieties and no
  language column: detecting the language is part of the job.
* Texts also contain typos, SMS spellings, emojis, internal jargon in staff notes (`frzr`, `GRN`, `OOS`, `FEFO`, `SM`, `AMC`),
  speech-recognition errors and `[inaudible]` in call transcripts, and truncated texts.
* The four channels genuinely write differently and cover different issues. The same real-world event is sometimes reported in
  several channels within a few days.
* Store sizes differ hugely (an Express store gets a small fraction of a Hyper's feedback). **Raw counts must be normalised**
  (adjusted for store size).
* Feedback is unverified. A single angry post is not proof of a systemic problem.
* **Not every spike is an emerging store problem.** Seasonality, festivals and chain-wide events also move the numbers.
* `store_id` is often missing for online reviews and app comments. Star ratings are sometimes inconsistent with the text.
* Some short texts are inherently ambiguous. For example, "the staff were very rude" could be unhelpful staff or misconduct.
  The labels follow one consistent annotation guideline, and identical texts always carry the same issue type.
* Labels exist only for a sample. Rare issue types were deliberately over-sampled (picked more often), so that every type has at
  least 30 labelled examples. So class frequencies in the labelled sample differ from the full stream.

## Train / test split

* The stream covers 26 weeks, **2026-03-30 → 2026-09-27**.
* **Training labels:** published for a sample of 3,000 records from **weeks 1–13** (30 Mar – 28 Jun 2026).
* **Test labels:** about 4,000 records from **weeks 14–26** (29 Jun – 27 Sep 2026) carry hidden labels. Rare types are
  over-sampled to at least 40 each.
* You don't know which records are in the test, so **predict every row of `feedback.csv`**.
* **Emerging incidents:** emerging-issue detection is scored on **three planted incidents** hidden in the stream. Their store(s),
  type and timing are secret.
* **Public worked example:** `IT17` at store `ST-D69EG`, onset week of 2026-04-27, naive detection week
  2026-05-18. It shows what an incident looks like and lets you compute the lead-time score locally. It is *not* one of the three.

## What to submit

### Your zip

Your team zip is `teamID_R5.zip`. Inside it, a folder `submission/` holds **three** files. Your detector code goes in `FULL_CODE/`, with the rest of your code.

```
teamID_R5.zip                  a zip of your project (a fresh git clone)
├── README.md                  how to set up and run your code
├── submission/
│   ├── R5_predictions.csv
│   ├── R5_emerging_flags.csv
│   └── detector_cmd.txt
└── FULL_CODE/                 This folder should contain all of your code:
                               your demo app + the code that created the
                               submission/ files
                               (including your detector and classifier)
```

**Your code is required too.** Every team submits one zip of its whole project, as the *Participant Coding Guidelines* explain (zip a fresh `git clone` of your project). The zip holds **all** your code, not only the code that makes your submission files: also the code of the solution you demo (for example a web or mobile app, dashboard, API, command-line tool or notebook). It also holds your own `README.md` that explains how to set up and run everything. It is fine if everything sits inside one project folder in the zip.

- Write your **own** `README.md`. The *Participant Coding Guidelines* (rule 12) list what it must cover. If you built inside this pack's folder, replace this pack's README with yours (rename this one to `PACK_README.md` if you want to keep it).
- Put **all** your code inside a folder named exactly `FULL_CODE/`, at the top of your project: your demo app + the code that created the `submission/` files. At the top of your project, keep only `README.md`, `submission/`, `FULL_CODE/` and your `.gitignore` (plus a `LICENSE` file if you have one).
- Put `submission/` at the top of your project, next to your `README.md`.
- Commit the files in `submission/` to git. Make sure your `.gitignore` does not exclude them (for example with `*.csv` or `*.jsonl`).
- Before you commit, list `data/`, `models/`, `.env`, `.venv/` and `node_modules/` in your `.gitignore`. This keeps the pack's data files and downloaded models out of your zip. Your README should say where to put the data and how to get any models.

| What | Required? | Section below |
|---|---|---|
| `submission/R5_predictions.csv` | **Required** | 1 |
| `submission/R5_emerging_flags.csv` | **Required** (it may have zero flag rows, but keep the header row) | 2 |
| `submission/detector_cmd.txt` | **Required** | 3 |
| The code that `detector_cmd.txt` runs, in `FULL_CODE/` | **Required** | 3 |
| A small model file you trained yourself, in `FULL_CODE/` (large downloaded models are not committed; see checklist item 7) | Optional | 3 |

`python baseline/baseline.py` writes all three `submission/` files in the right format (see "Hour Zero quick start").

### 1. `submission/R5_predictions.csv`: one label per record

```
feedback_id,issue_type_id,severity,actionable
FB-7K2Q9XLM,IT14,medium,1
```

Checklist:

1. One row for **every** `feedback_id` in `data/feedback.csv`.
2. No duplicate ids.
3. `issue_type_id` ∈ IT01–IT30, NI01–NI03.
4. `severity` ∈ low/medium/high/critical.
5. `actionable` ∈ 0/1.

### 2. `submission/R5_emerging_flags.csv`: your emerging-issue flags

A flag says: "in this week, at this store, this issue type is emerging". The file has zero or more rows:

```
as_of_week_start,store_id,issue_type_id,confidence,evidence_feedback_ids
2026-05-04,ST-4H2KQ,IT14,0.82,FB-AB12CD34;FB-EF56GH78;FB-IJ90KL12
```

| Column | Meaning |
|---|---|
| `as_of_week_start` | The Monday of the week in which you would raise the flag, **using only feedback up to that week's Sunday**. |
| `store_id` | The store you flag. |
| `issue_type_id` | The issue type you flag. |
| `confidence` | A number in [0, 1]. It is reported, **not scored**. |
| `evidence_feedback_ids` | The feedback_ids your flag is based on, `;`-separated. |

Checklist:

1. One row per (week, store, issue type). No two rows may share all three.
2. **Flags must be computed causally (as-of).** "Causally" means each week's flags use only feedback up to that week's Sunday,
   never later data. State this in your own README.
3. A flag only counts if it passes the **evidence rule** below.

#### The evidence rule

**A flag only counts if at least 2 of the cited ids pass all four checks:**

1. **(a) It exists:** the id is in `feedback.csv`.
2. **(b) It belongs to the flagged store:** either its `store_id` equals the flag's `store_id`, or its `store_id` is empty and
   the text names the store's locality. The locality is the part of `store_name` after "Saffron Hyper/Market/Express",
   e.g. "Kothrud". Upper/lower case does not matter.
3. **(c) It was created in that same week** (Monday–Sunday): from the Monday in `as_of_week_start` to the Sunday after it.
4. **(d) It is labelled with the flagged `issue_type_id` in your own `R5_predictions.csv`.**

**Important about check (d).** When you run `evaluate.py` yourself, check (d) uses the labels in your own `R5_predictions.csv`.
When the organisers score the test data, check (d) uses the **true** issue type of each cited record instead. So cite records
that really are about the flagged issue. Relabelling a few records in your predictions cannot make a flag pass.

Each cited id is counted once, even if you list it twice. Flags failing this rule are rejected. A rejected flag does not count
for detection, but it **still uses flag budget** (on average, at most 3 flags per week before your lead score is scaled down; see "How you're scored"). The `evaluate.py`
report says why flags were rejected.

Why this rule exists: a real escalation must be backed by that week's evidence. It also stops "flag the answer every week"
hindsight tricks (using knowledge you would not have had at the time).

#### Worked example: checking one flag

This example is imaginary. The ids below are not in the data. Take the example row above:

```
2026-05-04,ST-4H2KQ,IT14,0.82,FB-AB12CD34;FB-EF56GH78;FB-IJ90KL12
```

The flag's week runs from Monday 2026-05-04 to Sunday 2026-05-10. Imagine store `ST-4H2KQ` is named "Saffron Market Kothrud",
so its locality is "Kothrud". Now check each cited id:

| Cited id | Imagine this record has… | (a) | (b) | (c) | (d) | Counts? |
|---|---|---|---|---|---|---|
| `FB-AB12CD34` | `store_id` = `ST-4H2KQ`, created 2026-05-06, your label IT14 | yes | yes | yes | yes | **Yes** |
| `FB-EF56GH78` | `store_id` empty, text mentions "Kothrud", created 2026-05-09, your label IT14 | yes | yes | yes | yes | **Yes** |
| `FB-IJ90KL12` | `store_id` = `ST-4H2KQ`, created 2026-05-11, your label IT14 | yes | yes | **no** (next week) | yes | No |

Two ids pass all four checks, so the flag is **valid**.

Now imagine you had labelled `FB-EF56GH78` as IT01 in `R5_predictions.csv` (in your own `evaluate.py` run). Then only one id would pass. The flag would be
**rejected**, and it would still use flag budget.

### 3. `submission/detector_cmd.txt`: a runnable detector command (required)

Your zip must contain your detector code (in `FULL_CODE/`) and a one-line file `submission/detector_cmd.txt`.
See `sample_submission/detector_cmd.txt` for an example. Its one line is:

```
python baseline/baseline.py --feedback {feedback} --as-of {asof} --out {out}
```

Your command must have exactly this shape, written with the placeholders `{feedback}`, `{asof}` and `{out}`:

```
python <your_script> --feedback {feedback} --as-of {asof} --out {out}
```

That is, `python <your_script> --feedback <path_to_feedback.csv> --as-of YYYY-MM-DD --out <flags.csv>`.

Checklist for your detector command:

1. It has exactly the shape above. Keep the placeholders as written. They are filled in when the command is run for a check.
2. It runs from the top folder of your project (where your `README.md`, `submission/` and `FULL_CODE/` are). So your
   script path starts with `FULL_CODE/`, for example `python FULL_CODE/detect.py --feedback {feedback} --as-of {asof} --out {out}`.
3. It writes the flags for the week containing `--as-of` to the `--out` file. It uses the same columns as
   `R5_emerging_flags.csv`, including `evidence_feedback_ids`.
4. It uses **only rows with `created_at` ≤ that week's Sunday 23:59:59**.
5. It uses your own classifier, trained only on the public labelled sample.
6. No internet. At most 10 minutes per week on a laptop CPU.
7. **It reads every data file from the folder that contains `--feedback`**: `feedback.csv`, `feedback_labels_train.csv`,
   `store_master.csv`, `issue_taxonomy.csv`, `week_calendar.csv`. Do not read data files from anywhere else.
   Model files are different. A small model file you trained yourself may be committed in your project. A large downloaded
   model (for example an embedding model) may be loaded from a local cache, and your README must say how to download it.
   Training at run time from `feedback_labels_train.csv` in that folder is fine too.
8. Never hard-code dates, week numbers, store ids or feedback ids.
9. Your submitted `R5_emerging_flags.csv` should be exactly what this command produces, week by week, on the real data.

#### Worked example: filling in the placeholders

Here is how a command is filled in. Take the sample line above and fill in the placeholders:

| Placeholder | Example value |
|---|---|
| `{feedback}` | `data/feedback.csv` |
| `{asof}` | `2026-07-13` |
| `{out}` | `week.csv` |

The result is a working example to fork. You can run it from this folder:

```
python baseline/baseline.py --feedback data/feedback.csv --as-of 2026-07-13 --out week.csv
```

It writes `week.csv` with the flags for the week from Monday 2026-07-13 to Sunday 2026-07-19.
It uses only feedback up to that Sunday. Test your own command the same way, with your own script in place of `baseline/baseline.py`.

#### How the no-future-data rule is checked

* The organisers analyse your submitted flags and your code for signs of hindsight.
* They may also ask you to run your detector command **on your own laptop, in front of the jury**, for every scored week (13 weeks, so keep
  your detector fast). If they do, **your lead-time score is computed from the flags of that run, not from your submitted file.**
* For that run, the folder that contains `--feedback` is a *disguised* copy of `data/`:
    * feedback_ids and store_ids are replaced by fresh random ids. This is done consistently across all files. Store names and
      localities are unchanged.
    * All dates, including `--as-of` and `week_calendar.csv`, are shifted by a whole number of weeks.
    * So never hard-code dates, week numbers, store ids or feedback ids, and do not read data files from anywhere else
      (checklist items 7 and 8).
* These flags are treated as hindsight:
    * flags that cannot be reproduced;
    * flags that cite feedback your command was not given;
    * flags that only appear when the real ids/dates are present.
* Hindsight flags will be disqualified.
* The run may be repeated on a second disguised copy that contains a fresh, unseen emerging issue, to check that your
  detector really detects.

## How you're scored

`evaluate.py` computes (all constants are at the top of the file):

```
classification = 0.5 × macro-F1(issue_type) + 0.25 × weighted-F1(severity) + 0.25 × F1(actionable = 1)
lead_weeks_i   = naive_detect_week_i − your_detect_week_i, clipped to [−2, +4]   (never flagged → −2)
lead_score     = mean over the 3 incidents of (lead_weeks_i + 2) / 6
                 × min(1, 3 / average flags per week)
average flags per week = (your flags dated in weeks 14–26) / 13   for the hidden test
                         (your flags dated in weeks 1–13)  / 13   when scoring the public train truth
primary_score  = 0.6 × classification + 0.4 × lead_score     (range 0–1, higher is better)
```

What each line means:

* **classification**: how well you label records, from 0 to 1 (1 = perfect).
    * F1 is a score from 0 to 1. It balances precision (how many of your picks are right) and recall (how many true cases you found).
    * Macro-F1 = the plain average of the F1 for each issue type. Rare and common types count equally.
    * Weighted-F1 = the average of the F1 for each severity level, weighted by how many records have that level.
    * F1(actionable = 1) = the F1 for finding the actionable records.
* **lead_weeks_i**: how many weeks before the naive detector you caught incident *i*. Positive is good (you were earlier).
  It is capped at +4 and never goes below −2.
* **lead_score**: each incident's lead becomes a score from 0 to 1: −2 → 0, 0 → 1/3, +4 → 1. These are averaged over the 3
  incidents, then multiplied by the flood factor `min(1, 3 / average flags per week)`.
* **average flags per week**: all your flags dated in the scored 13 weeks, divided by 13. Rejected flags count here too.
* **primary_score**: 60% classification plus 40% lead score. This is your main score.

Details:

* Classification is computed only on the hidden-label records (macro-F1 averages over the issue types present there).
  When you practise with `data/feedback_labels_train.csv`, it is computed on those training labels instead.
  A missing prediction counts as wrong.
* **your_detect_week** for an incident = the earliest `as_of_week_start` that meets all of these:
    1. It is on or after the incident's onset week.
    2. You have a **valid** flag there (see the evidence rule).
    3. The flag's `store_id` is one of the incident's stores, from the week the incident reached that store
       (`store_first_week_starts`).
    4. The flag's `issue_type_id` equals the incident's type.
* **naive_detect_week** = the first week (from onset on) in which the chain-wide count of that issue type exceeds
  mean + 3 × max(sd, √mean, 1) of the previous up-to-8 weeks. (sd = standard deviation: how much the weekly count usually varies.)
* Each week earlier earns +1/6 for that incident. 4 weeks earlier = full marks; matching it = 1/3.
* For some incidents the naive rule fires fewer than 4 weeks after onset, so full marks need a flag in the onset week.
* **Flooding is penalised**: more than 3 flags per week on average (over the scored 13 weeks) scales your lead score down
  proportionally. Example: 52 flags in the scored 13 weeks = 4 per week, so your lead score is multiplied by 3/4.
* Flags dated outside the scored half are ignored, and `store_id` is matched case-insensitively.
* The report also prints your **precision statement** and your flag precision. The precision statement says: of the records you
  marked actionable, and of those you marked actionable and high/critical, what fraction truly are. Quote them in your presentation.
* The hidden-split score is **20%** of judging. Rubric: Problem framing 20%, Technical soundness 25%, Score on hidden split 20%,
  Real-world usability 15%, Responsibility 15%, Demo 5%.

#### Worked example: lead time for the public incident

The public worked example is `IT17` at store `ST-D69EG`. Its onset week is 2026-04-27 and its naive detection week is
2026-05-18. Your score for it depends on the week of your first **valid** `IT17` flag at `ST-D69EG`:

| Your first valid matching flag | lead_weeks | Incident score = (lead_weeks + 2) / 6 |
|---|---|---|
| 2026-04-27 (the onset week) | +3 | 5/6 ≈ 0.83 |
| 2026-05-04 | +2 | 4/6 ≈ 0.67 |
| 2026-05-11 | +1 | 3/6 = 0.50 |
| 2026-05-18 (same week as the naive detector) | 0 | 2/6 ≈ 0.33 |
| 2026-05-25 | −1 | 1/6 ≈ 0.17 |
| 2026-06-01 or later, or never | −2 | 0 |

Here the naive rule fires 3 weeks after onset, so +3 is the best possible lead.

## Hour Zero quick start

You need Python ≥ 3.9 with `pandas` and `numpy`. Run these three commands from this folder, one at a time.
On Mac/Linux, type `python3` instead of `python`.

```bash
python baseline/baseline.py
python evaluate.py --submission submission/R5_predictions.csv --truth data/feedback_labels_train.csv
python -m json.tool score.json
```

What they do:

1. `python baseline/baseline.py` runs the baseline. It makes your **test submission**: it writes `submission/R5_predictions.csv`
   (a prediction for every row, test weeks included), `submission/R5_emerging_flags.csv` and `submission/detector_cmd.txt`.
2. `python evaluate.py …` scores those files against the training labels. It prints a report and saves it in `score.json`.
3. `python -m json.tool score.json` shows `score.json` in a readable way.

Scoring against `data/feedback_labels_train.csv` uses the public worked example for the lead-time part. So you can check your
detector end-to-end before submitting.

**Check your setup:** the baseline should print `PRIMARY SCORE` ≈ **0.48** on the training labels
(classification ≈ 0.58, lead ≈ 0.33). On the hidden test it scores about **0.48**.

## Assumptions you may make

* Feedback is unverified; a single angry review is not proof of a systemic issue.
* Volume differs hugely by store size, so raw counts must be normalised.
* Anything mentioning safety, allergens, hygiene, or staff misconduct is high-severity by policy, regardless of volume.
* No audio is provided (transcripts only).

## Licence
Synthetic data generated for the TalentAP Mega Hackathon 2026. CC BY 4.0. Contains no real personal data.
