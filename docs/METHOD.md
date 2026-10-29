# Method and operating notes

## Data window

The live pipeline uses the computer's current local time and a trailing 365-day window. Snapshot folder names use UTC. Raw review timestamps keep the scraper representation. The public example was reconstructed from the supplied 2,800-row export at `2026-10-29T22:11:10`, excluding six rows before the cutoff. Its 2,794-row count matches the supplied run log. This reconstructed cutoff assumes the local machine was using India time; the original run's archived metadata is preferable when available.

Live analysis uses the freshly fetched window, not stale retained rows from the historical archive. Offline mode uses the saved file and labels that limitation. A cutoff at the end of a day may select a slightly different cohort from a live run earlier that day.

## Reading the numbers

All-star metrics use all reviews in the window. Negative means one or two stars. Issue triage uses one to three stars. Theme shares use that triage denominator and overlap. Status counts partition the triage set, while the human-review queue can include several statuses. A rule match identifies language to inspect; it does not prove an incident or its cause.

The store snapshot and fetched written-review sample have different populations. Changes in sample averages are descriptive. Version comparisons are not causal release experiments. The first and last calendar months can be incomplete.

## Suggested weekly workflow

Run the script, inspect the coverage label and latest report, then review safety signals and unmatched examples. Confirm actionable issues with product telemetry. Route each verified issue to the suggested function with evidence, expected behaviour and a measurable acceptance condition. Record the decision externally; this prototype does not send messages or create tickets.

## Optional scheduling on your Windows computer

Scheduling is not enabled by this repository. After confirming a manual run, you can create a Windows Task Scheduler task with a weekly trigger. Use the full path to `.venv\Scripts\python.exe` as the program, the quoted full path to `Pull_reviews.py` as the argument, and the project folder as the working directory. Configure it not to start another instance while one is running. The computer needs to be on and connected to the internet. Test the task manually and check its result and output files.

## Validation needed next

Have a person label a sample of matched and unmatched reviews. Measure false matches and missed themes, revise rules, then evaluate on a separate labelled sample. Validate product hypotheses using crash, login, booking and transport telemetry. No classifier accuracy or expected rating uplift is claimed.
