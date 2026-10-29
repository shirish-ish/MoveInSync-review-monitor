import pandas as pd
pd.set_option("display.max_colwidth", 160); pd.set_option("display.width", 220)

df = pd.read_csv("reviews_raw.csv", parse_dates=["at", "repliedAt"])
df["content"] = df["content"].fillna("")
d = df[df["at"] >= "2026-01-01"].copy()
neg = d[d["score"] <= 2].copy()
txt = neg["content"].str.lower()

THEMES = {
 "Login / OTP / session": r"\blog ?(?:in|out)\b|logged|sign ?(?:in|out)|\botp\b|session|password|terms and (?:agreement|condition)",
 "Tracking / ETA / pickup time": r"\bgps\b|\btrack|\beta\b|estimated|pick ?-?up time|\btimings?\b|wrong (?:place|location)|incorrect (?:location|time)",
 "Late / early / no-show": r"\blate\b|delay|\bearly\b|no[- ]?show|didn'?t come|not come|missed|\bwait",
 "Calling / contacting driver": r"(?:call|contact|chat|message).{0,25}driver|driver.{0,25}(?:call|phone|response)|calling option|no calling",
 "Booking / scheduling / seat": r"\bbook|schedul|roster|\bcancel|\bdesk\b|parking|\bseat (?:number|booking)",
 "Feedback / rating / popups": r"feedback|\brating\b|\brate\b|pop ?-?ups?",
 "Support / helpdesk": r"support|helpdesk|help desk|customer (?:care|service)|escalat|reach out|no response|nobody|no one",
 "Crashes / slow / bugs": r"\bcrash|\bhang(?:s|ing|ed)?\b|freez|\bstuck\b|\bslow\b|\blag(?:s|gy|ging)?\b|loading|takes (?:so much|forever)|not responding|\bbugs?\b|glitch|not working|server error|reinstall|uninstall|not installed",
 "Notifications": r"notif|reminder",
 "Safety-check friction": r"seat ?(?:belt|buckle)|buckle",
 "Driver conduct (ops)": r"\brude\b|misbehav|uncooperative|shout|abus",
}
for t, p in THEMES.items():
    neg[t] = txt.str.contains(p, regex=True)
neg["no_theme"] = ~neg[list(THEMES)].any(axis=1)

rows = [(t, int(neg[t].sum()), round(neg[t].mean() * 100, 1)) for t in list(THEMES) + ["no_theme"]]
print(f"2026 negatives: {len(neg)}")
print(pd.DataFrame(rows, columns=["theme", "n", "pct_of_negative"]).sort_values("n", ascending=False).to_string(index=False))
print("\nNote: themes overlap, so percentages do not add to 100.")

# Reply rate by year (confirms the 2026 drop)
df["replied"] = df["replyContent"].notna()
print("\n--- Reply rate by year (%) ---")
print((df.groupby(df["at"].dt.year)["replied"].mean() * 100).round(1))

# Pooled release bands
def band(v):
    try:
        major, minor = str(v).split(".")[:2]
        if major != "12": return "other"
        m = int(minor)
    except Exception:
        return "unknown"
    if m <= 9: return "12.8-12.9"
    if m <= 12: return "12.10-12.12"
    if m <= 14: return "12.13-12.14"
    return "12.15-12.20"

d["band"] = d["appVersion"].apply(band)
print("\n--- Release bands (2026) ---")
print(d.groupby("band").agg(n=("score", "size"), avg=("score", "mean"),
                            one_star_pct=("score", lambda s: (s == 1).mean() * 100)).round(2))

neg.to_csv("neg_2026_labelled_v2.csv", index=False)