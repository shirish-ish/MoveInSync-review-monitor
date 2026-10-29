"""Collect and analyse the latest 365 days of MoveInSync reviews.

Run: python Pull_reviews.py
Offline test: python Pull_reviews.py --offline --as-of 2026-10-29
Uses the same google-play-scraper dependency as the original collector.
Reads newest-first until crossing the rolling 365-day cutoff. --max-reviews
is a safety ceiling, not the analysis window. Reaching it early aborts the run.
Edits/deletions outside the fetched window are NOT detected. Retained records are
last-observed values, not proof that reviews still exist on the store.
Snapshot names use UTC. Review timestamps retain the source representation.
"""

import argparse
import csv
from datetime import datetime, timezone, timedelta, time as clock_time
from collections import Counter, defaultdict
from html import escape
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sys
import tempfile
import time

APP_ID = "com.moveinsync.ets"
LANG = "en"
COUNTRY = "in"
FIELDS = ["reviewId", "userName", "userImage", "content", "score",
          "thumbsUpCount", "reviewCreatedVersion", "at", "replyContent",
          "repliedAt", "appVersion"]


def normalize(row):
    if not set(FIELDS).issubset(row):
        raise ValueError("Review schema changed: required columns are missing.")
    out = {k: "" if row[k] is None else str(row[k]) for k in FIELDS}
    if not out["reviewId"].strip() or out["score"] not in {"1", "2", "3", "4", "5"}:
        raise ValueError("Missing review ID or invalid score; stopping before CSV replacement.")
    datetime.fromisoformat(out["at"])
    if out["repliedAt"]:
        datetime.fromisoformat(out["repliedAt"])
    return out


def load_existing(path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or []) != set(FIELDS):
            raise ValueError("Unexpected existing CSV columns; refusing to discard columns.")
        rows = {}
        for raw in reader:
            row = normalize(raw)
            if row["reviewId"] in rows:
                raise ValueError("Existing CSV has duplicate review IDs; review it before refreshing.")
            rows[row["reviewId"]] = row
        return rows


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def retry(call):
    for attempt in range(3):
        try:
            return call()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def collect(fetch_page, limit, since):
    fetched, token, count = {}, None, 0
    while count < limit:
        batch, next_token = retry(lambda: fetch_page(token, min(200, limit - count)))
        if not batch:
            raise RuntimeError("An empty review page was returned; existing CSV was not replaced.")
        before = len(fetched)
        for raw in batch[:limit - count]:
            row = normalize(raw)
            fetched[row["reviewId"]] = row
        count += min(len(batch), limit - count)
        if len(fetched) == before:
            raise RuntimeError("Pagination repeated the same reviews; existing CSV was not replaced.")
        print(f"Fetched {count:,} records ({len(fetched):,} unique)", flush=True)
        if min(datetime.fromisoformat(r["at"]) for r in fetched.values()) < since:
            return fetched, count, "cutoff_reached"
        if count >= limit:
            raise RuntimeError("Safety cap reached before covering one year. Increase --max-reviews; "
                               "existing CSV/report were not replaced.")
        # The scraper returns a token OBJECT even when its inner token is None.
        if not getattr(next_token, "token", next_token):
            # An end token may also follow an internal scraper error.
            return fetched, count, "source_end_unverified"
        token = next_token
    raise RuntimeError("Could not cover the requested window.")


# Conservative triage rules, not a validated classifier or root-cause model.
# All matches carry their evidence phrase; ambiguous OTP stays separate.
RULES = {
    "Safety investigation": r"\bsos\b|\bunsafe\b|speed limit|harass|assault",
    "Blocking prompts": r"pop[- ]?ups?|terms and (?:conditions|agreements)|policy acceptance|"
                        r"(?:forc\w*|mandator\w*).{0,55}(?:rat\w*|review|feedback)|"
                        r"(?:rat\w*|review|feedback).{0,55}(?:forc\w*|skip|block|can't|cannot)|"
                        r"(?:can't|cannot).{0,45}(?:skip|rate)|disclaimer",
    "Booking reliability": r"\bbook(?:ing|ings|ed)?\b|roster|wait[- ]?list|\bcancel\w*|"
                           r"schedules?.{0,30}(?:missing|not|empty)|\b(?:am|pm).{0,15}(?:confus|marker)",
    "Authentication": r"(?:unable|can't|cannot|not able|error).{0,35}\b(?:log ?in|sign ?in)\b|"
                      r"\b(?:log ?in|sign ?in)\b.{0,35}(?:error|fail|otp|issue)|"
                      r"(?:logged|logging|logs)[ -]?(?:out|off)|session (?:expired|expiry)|"
                      r"(?:every time|everytime|always|again).{0,35}\blog ?in\b|"
                      r"(?:sso|authentication|fingerprint login)|"
                      r"\bsign(?:s|ed)? out\b.{0,20}(?:every|automatic)|"
                      r"(?:register|sign up|verif\w*).{0,35}(?:otp|number|email)|"
                      r"otp.{0,35}(?:login|log in|email|mail|phone|mobile|whatsapp)",
    "App stability": r"\bcrash\w*|\bhang(?:s|ing|ed)?\b|freez\w*|\bbugs?\b|glitch\w*|"
                     r"\bslow\b(?! down)|\blag(?:s|gy|ging)?\b|loading|blank screen|"
                     r"(?:not|doesn't|won't|unable to|can't).{0,12}open|"
                     r"clos\w*.{0,25}(?:open|sec)|not (?:installed|downloaded).{0,20}play ?store|"
                     r"reinstall|uninstall|(?:takes?|taking).{0,25}(?:load|open)|"
                     r"app.{0,20}(?:not working|not responding|stopped working)",
    "Tracking and ETA": r"\beta\b|\bgps\b|\btrack\w*|pick[- ]?up time|"
                        r"(?:wrong|incorrect|inaccurate|stale).{0,20}(?:location|timing)|"
                        r"location.{0,35}(?:wrong|inaccurate|not|stuck|updat)|"
                        r"timings?.{0,25}(?:chang|incorrect|wrong)",
    "Boarding": r"seat ?(?:belt|buckle)|\bqr\b|\bboarding\b|"
                r"(?:view|boarding|driver).{0,15}\botp\b|otp.{0,25}(?:seat ?belt|board)",
    "Driver contact": r"(?:unable|can't|cannot|no option).{0,30}(?:call|contact).{0,20}driver|"
                      r"(?:no|disable\w*).{0,15}calling|calling.{0,20}disabled|"
                      r"driver.{0,25}(?:not respond|not pick|doesn't pick)|"
                      r"(?:chat|messag\w*).{0,40}driver|driver.{0,30}(?:audio|audible)|"
                      r"voice.{0,15}(?:not|inaudible)",
    "Support": r"help ?desk|customer (?:care|service|support)|support team|"
               r"(?:no|poor|useless|bad|zero|waste) support|\bescalat\w*|helpline",
    "Transport operations": r"rout(?:e|es|ing)|clubbing|\bno[- ]?show\b|"
                            r"\b(?:late|early)\b|cab.{0,30}(?:assign|allocat)|"
                            r"\bdriver\w*.{0,25}(?:rude|misbehav|abus|wait)|"
                            r"(?:rude|abus\w*).{0,20}driver",
}
# Additional issue phrases found during review of the supplied dataset.
# Keep these readable and testable; a match is a triage signal, not a diagnosis.
RULES["Authentication"] += (r"|\blogout(?:ing)?\b.{0,35}(?:sometimes|automatic|frequent)|"
    r"(?:not getting|can't|cannot|unable).{0,15}\blogin\b|"
    r"\blogin\b.{0,15}(?:nhi|nahi)|validate (?:my |your )?identity|no active subscription")
RULES["Safety investigation"] += r"|\bdangerous\b|(?:no|not).{0,10}\bsafety\b"
RULES["Tracking and ETA"] += (r"|\bmap\w*.{0,35}(?:stuck|wrong|not|updat)|"
    r"(?:updat\w*|realtime).{0,35}\bmaps?\b|"
    r"(?:location|arrival).{0,100}(?:hours? ago|not.{0,15}accurate|chang\w*)|"
    r"(?:pickup|pick up).{0,25}(?:location|building|floor)|estimated arrival")
RULES["Driver contact"] += (r"|(?:two way|two-way) communication|"
    r"(?:driver\w*|cabbies).{0,30}(?:do not|don't|does not|doesn't).{0,15}communicat|"
    r"\bchat\b.{0,35}(?:option|location|feature)|"
    r"(?:driver\w*|cabbies).{0,25}(?:didn't|did not).{0,10}respond")
RULES["Support"] += r"|transport (?:help|support) team|admin team|sahayta|saheta|(?:no|never).{0,15}(?:answer|response).{0,30}feedback"
RULES["Transport operations"] += (r"|schedule adherence|transport management|"
    r"shift.{0,20}starts|(?:cab|transport).{0,20}allocat|"
    r"driver\w*.{0,30}(?:behave|train)|no proper (?:management|coordination)")
RULES["App stability"] += r"|\bnot responding\b|\bnot opening\b|\bwon't open\b|\bdoesn't open\b"
RULES["Blocking prompts"] += r"|(?:review|rating|feedback).{0,25}(?:forced|mandatory)|(?:rate|rating).{0,30}skip|(?:keeps|always).{0,25}asking.{0,15}rating"
RULES.update({
    "Workplace / parking": r"\bparking\b|\bdesk\b|desk allocation|default floor|floor details.{0,20}booking",
    "Metro tickets": r"\bmetro\b",
    "Feedback controls": r"(?:no|missing|disabled|not|can't|cannot|doesn't).{0,30}(?:feedback|rating) (?:option|link)|"
                         r"(?:feedback|rating).{0,25}(?:disabled|not working|option|text box)|"
                         r"(?:trip rating|rate.{0,15}trip).{0,20}disabled|"
                         r"(?:only|limiting).{0,50}(?:4 or 5|high ratings)|doesn't allow feedback|"
                         r"no way to rate|no feedback option",
    "Notifications": r"notif\w*|message alerts|\breminders?\b",
    "Permissions": r"\bpermission\w*|microphone access",
    "Navigation / address UX": r"\bui\b|\bux\b|user[- ]friendly|unintuitive|"
                               r"confus\w*|complicated|(?:change|edit).{0,15}(?:address|destination)|"
                               r"(?:address|destination).{0,25}(?:chang|edit|wrong|missing)|"
                               r"navigating inside|error message.{0,30}(?:truncated|read)",
    "Connectivity / offline access": r"\boffline\b|(?:no|poor|lost|lose|losing).{0,15}(?:signal|network|connectivity)|"
                                     r"(?:network|internet).{0,25}(?:error|connection)|"
                                     r"(?:wifi|wi-fi|mobile data).{0,30}(?:only|work)|"
                                     r"(?:not|only).{0,25}(?:wifi|wi-fi|mobile data)",
})
PLAYBOOK = {
    "Safety investigation": (0, "Mobile + safety operations", "Reproduce reported emergency-access or unsafe-trip concerns urgently; verify escalation and acknowledgement. Reports are unverified.", "Emergency-action reachability and acknowledgement"),
    "Blocking prompts": (1, "Mobile + product", "Make feedback/promotional prompts dismissible and nonblocking; persist consent by policy version.", "Access to current trip without mandatory feedback"),
    "Booking reliability": (1, "Mobile + backend + QA", "Test date/time selection and confirmation versus trip-list state; show confirmed/waitlisted status and stable booking IDs.", "Booking success and confirmed-trip visibility"),
    "Authentication": (1, "Authentication + mobile", "Separate OTP delivery failures from session expiry; reproduce affected login paths and respect enterprise SSO policies.", "Login success, OTP delivery and unexpected session expiry"),
    "App stability": (1, "Mobile + QA", "Reproduce launch, install-source, crash and performance complaints by device and version; do not disable integrity protections.", "Successful launches and crash-free sessions"),
    "Tracking and ETA": (2, "Mobile + dispatch backend", "Verify stale tracking and pickup-time changes; show freshness and protect permitted trip details during connectivity loss.", "Tracking freshness and ETA error"),
    "Boarding": (2, "Mobile + safety operations", "Reproduce QR/boarding-code failures and obstructive boarding screens while preserving required safety checks.", "Successful boarding verification"),
    "Driver contact": (2, "Mobile + transport operations", "Test approved driver-contact paths; explain enterprise restrictions and expose an alternative contact route.", "Contact connection success"),
    "Support": (2, "Support + customer success", "Route complaints to issue owners with specific next steps; link review replies to resolution tracking.", "Acknowledgement and resolution rate"),
    "Transport operations": (2, "Transport desk + dispatch", "Investigate routing, allocation and disputed no-shows with operational records before assigning root cause to the app.", "Travel-time excess and disputed no-shows"),
    "Workplace / parking": (2, "Workplace product + backend", "Investigate parking/desk allocation, stale bookings and floor selection separately from transport self-booking.", "Valid workplace reservations and correct allocation visibility"),
    "Metro tickets": (2, "Metro integration + mobile", "Test ticket purchase, QR availability and entry/exit under weak connectivity separately from cab boarding.", "Purchased tickets available at entry and exit"),
    "Feedback controls": (2, "Product + mobile", "Test whether users can voluntarily submit all rating levels and written feedback; distinguish feedback controls from public review sentiment.", "Feedback submission success and available rating choices"),
    "Notifications": (2, "Mobile + messaging backend", "Check missing, late and repeated messages separately; deduplicate repetitive notices and preserve essential trip alerts.", "Trip-alert delivery latency and duplicate notification rate"),
    "Permissions": (2, "Mobile + security", "Explain each permission and request it in context. Review complaints about mandatory permissions without bypassing justified controls.", "Permission-related blocked journeys"),
    "Navigation / address UX": (2, "Product design + mobile", "Review the cited screen and task, especially address selection and unclear controls; reproduce the user journey before redesigning.", "Task completion and avoidable input errors"),
    "Connectivity / offline access": (1, "Mobile + backend", "Test loss of network during the active trip; preserve permitted trip information with expiry/freshness checks and clear reconnect status.", "Access to permitted trip essentials during connectivity loss"),
}

GENERIC_WORDS = {"the", "a", "an", "very", "so", "too", "such", "most", "ever", "one", "of",
    "worst", "worse", "bad", "poor", "pathetic", "useless", "waste", "horrible", "terrible",
    "rubbish", "disgusting", "outdated", "worthless", "irritating", "stupid", "app", "apps",
    "application", "applications", "service", "services", "experience", "company", "transport",
    "transportation", "cab", "cabs", "provider", "and", "with", "this", "is", "its", "it",
    "i", "have", "used", "seen", "my", "life", "in", "not", "at", "all", "good", "nice",
    "best", "excellent", "normal", "okay", "ok", "bekaar", "bekar", "hai", "bhot", "bahut",
    "bakwaas", "bakwas", "wrost", "wast", "worrest"}


def feedback_status(text, matches):
    plain = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    words = plain.split()
    if plain in {"good", "good app", "nice", "nice app", "excellent", "best app", "it has good features"}:
        return "rating_text_mismatch"
    if matches:
        return "rule_matched"
    if words and len(words) <= 20 and set(words) <= GENERIC_WORDS:
        return "general_feedback_no_detail"
    return "unclassified_needs_review"


def classify(text):
    text = re.sub(r"\s+", " ", text.lower().replace("’", "'"))
    matches = {name: match.group(0) for name, pattern in RULES.items()
               if (match := re.search(pattern, text))}
    # Separate workplace/metro bookings unless transport is explicitly discussed too.
    if {"Workplace / parking", "Metro tickets"} & matches.keys():
        if not re.search(r"\b(?:cab|shuttle|bus|driver|roster)\b", text):
            matches.pop("Booking reliability", None)
            matches.pop("Boarding", None)
    if "Permissions" in matches and re.search(r"calling.{0,25}(?:disabled|policy)", text):
        matches.pop("Permissions", None)  # Company calling policy is not a phone permission.
    if re.search(r"\botps?\b", text) and not ({"Authentication", "Boarding"} & matches.keys()):
        matches["OTP context unclear"] = "otp"
    return matches


def statistics(rows):
    n = len(rows)
    scores = [int(r["score"]) for r in rows]
    return dict(n=n, average=round(sum(scores)/n, 3) if n else None,
                one_star_pct=round(100*scores.count(1)/n, 2) if n else None,
                negative_n=sum(s <= 2 for s in scores),
                replied_n=sum(bool(r["replyContent"].strip()) for r in rows))


def analyse(rows, since, until, metadata, coverage):
    # Only current-window fetched records enter live analysis, not stale retained rows.
    year = [r for r in rows if since <= datetime.fromisoformat(r["at"]) <= until]
    year.sort(key=lambda r: r["at"], reverse=True)
    low = [r for r in year if int(r["score"]) <= 3]
    groups, queue, labelled = defaultdict(list), [], []
    for r in low:
        matches = classify(r["content"])
        status = feedback_status(r["content"], matches)
        for theme in matches:
            groups[theme].append(r)
        reasons = []
        if status == "unclassified_needs_review":
            reasons.append("No rule match; may contain a missed issue")
        if status == "rating_text_mismatch":
            reasons.append("Positive text with a 1-3-star rating; check intent")
        if "OTP context unclear" in matches:
            reasons.append("Login versus boarding context is unclear")
        if "Safety investigation" in matches:
            reasons.append("Urgent human investigation; not a confirmed incident")
        if len(r["content"].strip()) < 30 and status == "rule_matched":
            reasons.append("Short text: insufficient context for a specific root cause")
        item = dict(reviewId=r["reviewId"], at=r["at"], score=r["score"],
                    appVersion=r["appVersion"], content=r["content"],
                    status=status, themes="; ".join(matches), matched_phrases=json.dumps(matches),
                    review_reason="; ".join(reasons))
        labelled.append(item)
        if reasons:
            queue.append(item)
    proposals = []
    for name, (priority, owner, action, metric) in PLAYBOOK.items():
        if groups[name]:
            def evidence_rank(r):
                text = r["content"].lower()
                safety = name == "Safety investigation" and bool(re.search(r"\bsos\b", text))
                return (safety, min(len(text), 350), r["at"])
            evidence = sorted(groups[name], key=evidence_rank, reverse=True)[:3]
            proposals.append(dict(theme=name, priority=priority, owner=owner, action=action,
                                  metric=metric, count=len(groups[name]),
                                  pct_low=round(100*len(groups[name])/len(low), 2),
                                  recent_30_n=sum(datetime.fromisoformat(r["at"]) >= until-timedelta(days=30) for r in groups[name]),
                                  evidence=[{k: r[k] for k in ("reviewId", "at", "score", "appVersion", "content")}
                                            for r in evidence]))
    proposals.sort(key=lambda p: (p["priority"], -p["count"], p["theme"]))
    months, versions = defaultdict(list), defaultdict(list)
    for r in year:
        months[r["at"][:7]].append(r)
        versions[r["appVersion"] or "unknown"].append(r)
    previous = [r for r in year if until-timedelta(days=60) <= datetime.fromisoformat(r["at"]) < until-timedelta(days=30)]
    recent = [r for r in year if until-timedelta(days=30) <= datetime.fromisoformat(r["at"]) <= until]
    result = dict(window_start=since.isoformat(), window_end=until.isoformat(), window_days=365,
                  coverage=coverage, app_id=APP_ID, language=LANG, country=COUNTRY,
                  metrics=statistics(year), low_rating_n=len(low), review_queue_n=len(queue),
                  no_rule_match_n=sum(not x["themes"] for x in labelled),
                  status_counts=dict(Counter(x["status"] for x in labelled)),
                  classifier_version="rules-v2", recommendation_method="Predefined playbooks selected by rule matches; no LLM API",
                  latest_30_days=statistics(recent), previous_30_days=statistics(previous),
                  monthly=[dict(month=k, **statistics(v)) for k,v in sorted(months.items())],
                  versions=[dict(version=k, **statistics(v)) for k,v in sorted(versions.items())],
                  store_snapshot=metadata, recommendations=proposals,
                  limitations=["Rule-based triage, not validated theme prevalence or a causal diagnosis.",
                    "Tools: Python standard library and google-play-scraper. Development and initial review were assisted by Claude and ChatGPT; runtime analysis uses no LLM API.",
                    "Recommendations use predefined engineering playbooks and require review.",
                    "Generic feedback without a concrete issue is retained separately, not treated as a specific defect.",
                    "Evidence examples favour detailed descriptions (SOS-related text first for safety), not a random sample.",
                    "Theme shares overlap and use 1-3-star reviews, not only 1-2 stars.",
                    "Self-selected fetched review sample; averages are not the displayed store rating.",
                    "Edited review dates can change cohorts. Reply delay is not calculated.",
                    "Partial boundary months and small version samples are not like-for-like comparisons.",
                    "Raw scraper timestamps and the cutoff use the computer's local clock."])
    return year, labelled, queue, result


def save_analysis(directory, year, labelled, queue, result):
    write_csv(directory / "reviews_latest_year.csv", year)
    for filename, rows in (("reviews_labelled.csv", labelled), ("needs_review.csv", queue)):
        fields = ["reviewId", "at", "score", "appVersion", "content", "status", "themes", "matched_phrases", "review_reason"]
        with (directory / filename).open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    write_json(directory / "review_summary.json", result)
    e = lambda value: escape(str(value))
    def table(rows, fields):
        return "<table><tr>" + "".join(f"<th>{e(k)}</th>" for k in fields) + "</tr>" + "".join(
            "<tr>"+"".join(f"<td>{e(r.get(k, ''))}</td>" for k in fields)+"</tr>" for r in rows)+"</table>"
    m = result["metrics"]
    parts = ["<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
             "<title>MoveInSync review monitor</title><style>body{font:16px system-ui;margin:40px auto;padding:0 24px;max-width:1050px;color:#172b39;background:#f7fafc}h1,h2{color:#123e53}section{background:white;padding:22px;margin:20px 0;border:1px solid #dbe4ea;border-radius:10px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}blockquote{border-left:3px solid #53788d;margin:12px 0;padding:12px;background:#f4f7f9}.note{color:#704813}small{overflow-wrap:anywhere}</style>",
             "<h1>MoveInSync review monitor</h1>",
             f"<p>{e(result['window_start'])} to {e(result['window_end'])} · Rolling 365 days</p>",
             f"<p class='note'>Coverage: {e(result['coverage'])}. Read limitations below.</p>",
             f"<section><h2>Review sample</h2><p>{m['n']:,} reviews · Average {m['average']} · One-star share {m['one_star_pct']}%</p>",
             f"<p>{m['negative_n']} one/two-star reviews; {result['low_rating_n']} one/ two/three-star reviews used for issue triage.</p>",
             f"<p>{result['review_queue_n']} reviews need closer inspection; {result['no_rule_match_n']} have no rule match.</p>",
             f"<p>Among these low-rated reviews, {result['status_counts'].get('general_feedback_no_detail', 0)} contain only general feedback, {result['status_counts'].get('unclassified_needs_review', 0)} remain unclassified, and {result['status_counts'].get('rating_text_mismatch', 0)} have a possible rating/text mismatch. See the labelled CSV for every status.</p>",
             f"<p>Store snapshot rating: {e(result['store_snapshot'].get('score', 'unavailable'))}; total ratings: {e(result['store_snapshot'].get('ratings', 'unavailable'))}. Separate from the sample average.</p></section>",
             "<section><h2>Recent periods</h2>", table([dict(period="Latest 30 days", **result['latest_30_days']),dict(period="Previous 30 days", **result['previous_30_days'])], ["period","n","average","one_star_pct"]), "</section>",
             "<h2>Suggested actions</h2><p>Rule-matched signals, not confirmed defects. Priority uses a predefined severity order, then matched count; validate scope and effort with the owner.</p>"]
    if not result["recommendations"]:
        parts.append("<p>No playbook matched. Inspect the review queue; this does not establish an absence of problems.</p>")
    for p in result["recommendations"]:
        parts += [f"<section><h2>P{p['priority']} · {e(p['theme'])}</h2><p>{p['count']} matching reviews ({p['pct_low']}% of 1-3-star reviews)</p>",
                  f"<p>{p['recent_30_n']} matches in the latest 30 days. Examples below are selected for detail, not necessarily recency.</p><p><b>Owner:</b> {e(p['owner'])}</p><p>{e(p['action'])}</p><p><b>Measure:</b> {e(p['metric'])}</p>"]
        for r in p["evidence"]:
            parts.append(f"<blockquote>{e(r['content'])}<br><small>{e(r['at'])} · {e(r['score'])} stars · Version {e(r['appVersion'])} · Review {e(r['reviewId'])}</small></blockquote>")
        parts.append("</section>")
    parts += ["<section><h2>Monthly trend</h2><p>First and last months can be incomplete.</p>",table(result["monthly"],["month","n","average","one_star_pct"]),"</section>",
              "<section><h2>Version cohorts</h2><p>Review counts are not installation counts. Differences are not proof of release causation.</p>",table(result["versions"],["version","n","average","one_star_pct"]),"</section>",
              "<section><h2>Method and limitations</h2><ul>",*(f"<li>{e(t)}</li>" for t in result["limitations"]),"</ul></section></html>"]
    (directory / "report.html").write_text("\n".join(parts), encoding="utf-8")


def publish_report_link(data_dir, run_dir):
    # The immutable run directory holds matching CSV, JSON and HTML outputs.
    # Replace one small pointer only after all outputs are successfully written.
    relative = run_dir.relative_to(data_dir).as_posix() + "/report.html"
    fd, name = tempfile.mkstemp(prefix="report_link_", suffix=".tmp", dir=data_dir)
    os.close(fd)
    temp = Path(name)
    try:
        temp.write_text(f"<!doctype html><html><meta charset='utf-8'><title>Latest review report</title><h1>Latest review report</h1><p><a href='{escape(relative, quote=True)}'>Open the latest completed report</a></p></html>", encoding="utf-8")
        os.replace(temp, data_dir / "latest_report.html")
    finally:
        temp.unlink(missing_ok=True)


def run(data_dir, limit, fetch_page, fetch_app, until=None):
    until = until or datetime.now()
    since = until - timedelta(days=365)
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    raw_path = data_dir / "reviews_raw.csv"
    lock_path = data_dir / "reviews_refresh.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("A refresh lock exists. Do not run twice at once. If a previous run "
                           "was forcibly stopped, confirm it has ended before removing reviews_refresh.lock.")
    os.close(descriptor)
    temporary = None
    try:
        original_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest() if raw_path.exists() else None
        old = load_existing(raw_path)
        print(f"Existing reviews: {len(old):,}")
        captured_at = datetime.now(timezone.utc).isoformat()
        info = retry(fetch_app)
        if not isinstance(info, dict) or any(info.get(k) is None for k in ("score", "ratings")):
            raise ValueError("Store rating metadata is missing; existing CSV was not replaced.")
        fresh, count, stop = collect(fetch_page, limit, since)
        new_count = sum(key not in old for key in fresh)
        changed = sum(key in old and old[key] != value for key, value in fresh.items())
        merged = {**old, **fresh}
        ordered = sorted(merged.values(), key=lambda r: r["at"], reverse=True)
        run_dir = data_dir / "snapshots" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        run_dir.mkdir(parents=True, exist_ok=False)
        if raw_path.exists():
            shutil.copy2(raw_path, run_dir / "reviews_before.csv")
        write_csv(run_dir / "reviews_fetched.csv", fresh.values())
        write_csv(run_dir / "reviews_after.csv", ordered)
        metadata = {k: info.get(k) for k in ("title", "score", "ratings", "reviews", "version", "updated", "url")}
        metadata.update(app_id=APP_ID, country=COUNTRY, language=LANG, captured_at_utc=captured_at)
        write_json(run_dir / "app_metadata.json", metadata)
        analysis = analyse(list(fresh.values()), since, until, metadata, stop)
        save_analysis(run_dir, *analysis)
        summary = dict(status="prepared", app_id=APP_ID, country=COUNTRY, language=LANG,
                       started_at_utc=captured_at, requested_limit=limit, fetched_records=count,
                       fetched_unique=len(fresh), existing=len(old), new=new_count,
                       updated=changed, unchanged_fetched=len(fresh)-new_count-changed,
                       retained_not_refetched=len(old.keys()-fresh.keys()), total=len(merged),
                       stop_reason=stop, previous_sha256=original_hash,
                       window_start=since.isoformat(), window_end=until.isoformat(),
                       coverage_note="Rolling 365-day refresh; older records retained. "
                       "Not a complete review history; removals and unobserved edits are not detected.")
        write_json(run_dir / "run_summary.json", summary)
        current_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest() if raw_path.exists() else None
        if current_hash != original_hash:
            raise RuntimeError("reviews_raw.csv changed during collection; refusing to overwrite it.")
        fd, name = tempfile.mkstemp(prefix="reviews_refresh_", suffix=".tmp", dir=data_dir)
        os.close(fd)
        temporary = Path(name)
        shutil.copyfile(run_dir / "reviews_after.csv", temporary)
        os.replace(temporary, raw_path)
        temporary = None
        summary.update(status="completed", finished_at_utc=datetime.now(timezone.utc).isoformat())
        write_json(run_dir / "run_summary.json", summary)
        publish_report_link(data_dir, run_dir)
        print(f"\nNew: {new_count:,} | Updated: {changed:,} | Total saved: {len(merged):,}")
        print(f"Store rating: {info['score']} | Total ratings: {info['ratings']}")
        if stop != "cutoff_reached":
            print("WARNING: source stopped before the date cutoff. This may be exhaustion or an upstream "
                  "error; coverage is unverified. Older rows were retained.")
        print(f"CSV: {raw_path}\nSnapshot: {run_dir}")
        print(f"Latest-year reviews: {analysis[3]['metrics']['n']:,}\nOpen: {data_dir / 'latest_report.html'}")
        return summary
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-reviews", type=int, default=20000)
    parser.add_argument("--offline", action="store_true", help="Analyse saved CSV only; no live store fetch or CSV replacement")
    parser.add_argument("--as-of", help="Offline only: YYYY-MM-DD, inclusive end of day")
    args = parser.parse_args()
    if args.max_reviews <= 0:
        parser.error("--max-reviews must be positive")
    if args.as_of and not args.offline:
        parser.error("--as-of is only supported with --offline")
    try:
        data_dir = Path(__file__).resolve().parent
        if args.offline:
            until = datetime.combine(datetime.strptime(args.as_of, "%Y-%m-%d").date(), clock_time.max) if args.as_of else datetime.now()
            rows = load_existing(data_dir / "reviews_raw.csv")
            if not rows:
                raise ValueError("No saved reviews available for offline analysis.")
            run_dir = data_dir / "snapshots" / ("offline_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ"))
            run_dir.mkdir(parents=True, exist_ok=False)
            result = analyse(list(rows.values()), until-timedelta(days=365), until, {},
                             "OFFLINE: saved sample only; not refreshed from Play Store")
            save_analysis(run_dir, *result)
            publish_report_link(data_dir, run_dir)
            print(f"Offline report: {run_dir / 'report.html'}\nReviews in window: {result[3]['metrics']['n']}")
            return 0
        from google_play_scraper import reviews, app, Sort
        run(Path(__file__).resolve().parent, args.max_reviews,
            lambda token, count: reviews(APP_ID, lang=LANG, country=COUNTRY,
                                        sort=Sort.NEWEST, count=count, continuation_token=token),
            lambda: app(APP_ID, lang=LANG, country=COUNTRY))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Check any snapshot run_summary.json status before rerunning. "
              "Close reviews_raw.csv in Excel if replacement was blocked.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
