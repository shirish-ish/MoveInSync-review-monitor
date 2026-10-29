# MoveInSync Review Monitor

A repeatable Python workflow that collects the latest 365 days of MoveInSync Google Play reviews, identifies complaint themes with rules, and produces an HTML report with suggested actions and a human review queue.

The project focuses on the self booking journey. It uses predefined engineering playbooks and requires no paid AI API. Recommendations are investigation proposals, not confirmed root causes or automatically applied fixes.

## Example results

The saved 29 October 2026 sample contains 2,794 reviews with an average rating of 3.84 and a one-star share of 23.94%. Of these, 754 have one or two stars and 823 have one to three stars. The latter group is used for issue triage.

The store snapshot was 4.64 across 115,589 ratings. This is a separate population from the fetched review sample; the difference does not establish a decline.

| Rule status among 823 reviews | Count |
| --- | ---: |
| Rule matched | 512 |
| General feedback without detail | 107 |
| Possible rating/text mismatch | 5 |
| Unclassified | 199 |

The human review queue contains 287 reviews because it also includes safety, ambiguous and short matches. Theme matches overlap; coverage is not accuracy.

Download [sample_report.html](examples/sample_report.html) and open it in a browser to view a report with aggregate results. GitHub's file view shows HTML source rather than a running dashboard. [sample_summary.json](examples/sample_summary.json) contains the same aggregate analysis. Review text and identifiers have been removed from these public examples.

## Run on Windows

Use Python 3.10 or newer. Open Command Prompt in this extracted project folder and run:

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe Pull_reviews.py
```

Open `latest_report.html` when the run finishes. An internet connection is required for collection. The script fetches newest-first until it crosses the rolling 365-day cutoff; 20,000 reviews is a safety ceiling, not a fixed sample size. If the ceiling is reached first, increase it deliberately:

```bat
.venv\Scripts\python.exe Pull_reviews.py --max-reviews 40000
```

If you already have a compatible `reviews_raw.csv`, copy it beside `Pull_reviews.py` to preserve the existing history. Back up your original project first. Do not run multiple collectors against the same folder simultaneously.

For macOS/Linux, use `python3 -m venv .venv`, then `.venv/bin/python` in place of `.venv\Scripts\python.exe`.

## Analyse an existing export without fetching

```bat
.venv\Scripts\python.exe Pull_reviews.py --offline --as-of 2026-10-29
```

This requires your own compatible `reviews_raw.csv`; raw reviews are not bundled. The date is interpreted as the end of that local day. Offline mode does not refresh reviews or store metadata. It is labelled as a saved sample. A different cutoff can change the review count; the bundled example uses the reconstructed original run cutoff recorded in its JSON.

## Files produced

| File | Use |
| --- | --- |
| `reviews_raw.csv` | Merged, last-observed review archive |
| `latest_report.html` | Link to the latest successfully generated report |
| `snapshots/<timestamp>/report.html` | Full report for that run |
| `snapshots/<timestamp>/reviews_latest_year.csv` | Reviews in the current window |
| `snapshots/<timestamp>/reviews_labelled.csv` | Low-rated reviews with matched phrases and themes |
| `snapshots/<timestamp>/needs_review.csv` | Items requiring closer human inspection |
| `snapshots/<timestamp>/review_summary.json` | Metrics and proposed actions |

Live snapshots also retain before/fetched/after records, metadata and a run summary. Inspect run status after a failure. Collection failures and a safety-cap failure do not replace the previous archive/report. A source-end response before the cutoff is explicitly marked as unverified coverage.

## How the rules work

1. Calculate rating metrics for all fetched reviews within the latest 365 days.
2. Examine one to three star reviews using keyword and regular expression rules.
3. Assign overlapping themes and retain the matched phrases.
4. Select predefined actions, suggested owners and outcome measures.
5. Order suggestions by predefined severity, then matched count.
6. Keep unknown, ambiguous, safety-related and short matches in a human queue.

Change the rule definitions and `PLAYBOOK` in `Pull_reviews.py` to refine matching and proposals. The app ID, language and country settings are constants near the top. Adapting this to another product also requires reviewing its rules and playbooks. This is not a validated universal classifier.

## Verify

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The 13 tests use synthetic records and mocked collection. They cover boundaries, deduplication, snapshots, error handling, report escaping and rule regressions. They do not establish accuracy on unseen reviews or validate a live Google Play integration.

## Project layout

- `Pull_reviews.py`: supported collection and analysis entry point.
- `tests/test_pipeline.py`: automated checks with synthetic examples.
- `examples/`: aggregate report and summary from the saved sample.
- `docs/EVIDENCE.md`: review IDs for case-study evidence.
- `docs/METHOD.md`: interpretation, limitations and optional scheduling.
- `exploration/`: original exploratory scripts retained for development history. These use fixed historical windows and earlier rules; do not use them to reproduce the current pipeline's counts. See its README.

## Limitations

Reviews are self selected and scraper coverage may be incomplete. Rules can misread context and miss wording or languages. Country/language retrieval settings do not prove reviewer location. Edited dates can change cohorts. Partial months and small version samples should not be treated as controlled comparisons. Store rating counts differ from collected written reviews. Historical records outside the fetched window are retained but are not revalidated for deletions or edits.

Public examples omit original review text. Local reports and CSVs may contain names or other personal details from reviews; inspect and redact them before sharing. `.gitignore` prevents common generated outputs from being added through Git, but does not protect files manually uploaded in a browser.

## Tools and development assistance

Python standard library and `google-play-scraper` power the current pipeline. Pandas was used in the earlier exploratory scripts. Claude and ChatGPT assisted code development and initial analysis. Runtime analysis makes no LLM API calls. Scheduling, external tickets and product fixes are not configured.
