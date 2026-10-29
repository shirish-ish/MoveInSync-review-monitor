import pandas as pd
pd.set_option("display.max_colwidth", 220)
pd.set_option("display.width", 250)

df = pd.read_csv("reviews_raw.csv", parse_dates=["at", "repliedAt"])
df["content"] = df["content"].fillna("")
df["month"] = df["at"].dt.to_period("M")

# 1. Which version families when?
df["ver_major"] = df["appVersion"].astype(str).str.split(".").str[0]
print("--- Version major: first/last review date, count ---")
print(df.groupby("ver_major")["at"].agg(["min", "max", "count"]).sort_values("min"))

# 2. 1-star share by year
df["is_1star"] = df["score"] == 1
print("\n--- 1-star share by year (%) ---")
print((df.groupby(df["at"].dt.year)["is_1star"].mean() * 100).round(1))

# 3. Monthly trend, last 24 months
recent = df[df["at"] >= "2024-11-01"]
m = recent.groupby("month").agg(n=("score", "size"), avg=("score", "mean"),
                                one_star_pct=("is_1star", lambda s: s.mean() * 100))
print("\n--- Monthly trend, last 24 months ---")
print(m.round(2))

# 4. Reply rate by star
df["replied"] = df["replyContent"].notna()
print("\n--- Reply rate by star (%) ---")
print((df.groupby("score")["replied"].mean() * 100).round(1))

# 5. Rough keyword counts in 1-2 star reviews since 2025
neg = df[(df["score"] <= 2) & (df["at"] >= "2025-01-01")]
keywords = ["login", "log in", "otp", "location", "gps", "track", "late", "driver",
            "cab", "crash", "update", "book", "schedule", "notification",
            "support", "call", "pickup", "roster", "slow", "not working"]
print(f"\n--- Keyword counts in {len(neg)} negative reviews since 2025 ---")
text = neg["content"].str.lower()
for k in keywords:
    print(f"{k:15s} {text.str.contains(k, regex=False).sum()}")

# 6. Most-upvoted negative reviews since 2025
print("\n--- Top 15 most thumbs-upped negative reviews since 2025 ---")
print(neg.sort_values("thumbsUpCount", ascending=False)
        [["at", "score", "appVersion", "thumbsUpCount", "content"]].head(15).to_string())

# 7. 30 random recent 1-star reviews
print("\n--- 30 random 1-star reviews since 2025 ---")
print(neg[neg["score"] == 1].sample(30, random_state=7)[["at", "appVersion", "content"]].to_string())