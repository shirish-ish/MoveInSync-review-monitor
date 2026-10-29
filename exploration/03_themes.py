import pandas as pd, re
pd.set_option("display.max_colwidth", 200); pd.set_option("display.width", 250)

df = pd.read_csv("reviews_raw.csv", parse_dates=["at", "repliedAt"])
df["content"] = df["content"].fillna("")
d = df[df["at"] >= "2026-01-01"].copy()
neg = d[d["score"] <= 2].copy()
print(f"2026 reviews: {len(d)} | avg {d.score.mean():.2f} | negative (1-2 star): {len(neg)} ({len(neg)/len(d):.0%})")

THEMES = {
 "Login / OTP / session":      r"log ?in|log ?out|logged|sign ?in|\botp\b|session|password|credential",
 "Tracking / ETA / location":  r"gps|track|location|\beta\b|estimated|pick ?-?up time|timing|map|wrong (place|location)",
 "Late / early / no-show":     r"\blate\b|delay|early|no[- ]?show|didn'?t come|not come|missed|waiting|\bwait",
 "Calling driver / contact":   r"\bcall(ing)?\b|phone|contact",
 "Booking / scheduling":       r"book|schedul|roster|cancel|\bseat\b|desk|parking|shift",
 "Feedback / rating UX":       r"feedback|rating|\brate\b|pop ?-?up",
 "Support / helpdesk":         r"support|helpdesk|help desk|customer (care|service)|escalat|reach out|no response|nobody|no one",
 "Bugs / crashes / speed":     r"crash|hang|freez|stuck|slow|lag|loading|bug|glitch|not working|server|error|internet|reinstall|uninstall|update",
 "Notifications":              r"notif|alert|reminder",
 "Safety checks / boarding":   r"seat ?belt|buckle|verification|safety",
 "Driver conduct (ops)":       r"rude|behav|uncooperative|misbehav|abus",
}
for t, p in THEMES.items():
    neg[t] = neg["content"].str.lower().str.contains(p, regex=True)
neg["no_theme"] = ~neg[list(THEMES)].any(axis=1)

# Theme share + illustrative lift (if theme reviews became 4-star, how much would the 2026 average rise?)
rows = []
for t in list(THEMES) + ["no_theme"]:
    m = neg[t]
    lift = ((4 - neg.loc[m, "score"]).sum()) / len(d)
    rows.append((t, m.sum(), round(m.mean() * 100, 1), round(lift, 3)))
res = pd.DataFrame(rows, columns=["theme", "n_reviews", "pct_of_negative", "avg_lift_if_fixed"])
print("\n--- Themes (2026 negative reviews) ---")
print(res.sort_values("n_reviews", ascending=False).to_string(index=False))

# Version table: which releases hurt?
d["ver"] = d["appVersion"].fillna("unknown")
v = d.groupby("ver").agg(n=("score", "size"), avg=("score", "mean"),
                         one_star_pct=("score", lambda s: (s == 1).mean() * 100),
                         first_seen=("at", "min")).query("n >= 20").sort_values("first_seen")
print("\n--- 2026 versions with >=20 reviews ---")
print(v.round(2).to_string())

# Replies on negatives
neg["replied"] = neg["replyContent"].notna()
neg["hrs_to_reply"] = (neg["repliedAt"] - neg["at"]).dt.total_seconds() / 3600
print(f"\nReply rate on 2026 negatives: {neg.replied.mean():.0%} | median hours to reply: {neg.hrs_to_reply.median():.1f}")
print("\n--- 8 sample developer replies ---")
print(neg[neg.replied]["replyContent"].sample(8, random_state=3).to_string())
print("\nDistinct replies / total replies:", neg[neg.replied]["replyContent"].nunique(), "/", neg.replied.sum())

# Top quote per theme + unlabelled sample
print("\n--- Most upvoted review per theme ---")
for t in THEMES:
    s = neg[neg[t]].sort_values("thumbsUpCount", ascending=False).head(2)
    print(f"\n[{t}]")
    print(s[["at", "appVersion", "thumbsUpCount", "content"]].to_string(header=False))

print("\n--- 25 reviews with NO theme (check for missed themes) ---")
print(neg[neg.no_theme][["content"]].sample(min(25, int(neg.no_theme.sum())), random_state=5).to_string())

neg.to_csv("neg_2026_labelled.csv", index=False)