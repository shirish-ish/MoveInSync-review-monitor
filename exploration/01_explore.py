import pandas as pd

df = pd.read_csv("reviews_raw.csv", parse_dates=["at", "repliedAt"])

print("Rows:", len(df))
print("\nColumns:", list(df.columns))

print("\n--- Star distribution ---")
print(df["score"].value_counts().sort_index())
print("\nAverage score of this sample:", round(df["score"].mean(), 2))

print("\n--- Reviews per year ---")
print(df.groupby(df["at"].dt.year).size())

print("\n--- Average score per year ---")
print(df.groupby(df["at"].dt.year)["score"].mean().round(2))

print("\n--- Empty text ---")
print("Missing/blank content:", (df["content"].fillna("").str.strip() == "").sum())

print("\n--- Developer replies ---")
print("Reviews with a reply:", df["replyContent"].notna().sum())

print("\n--- Top 10 app versions by review count ---")
print(df["appVersion"].value_counts().head(10))

print("\n--- Sample of 15 one-star reviews ---")
print(df[df["score"] == 1]["content"].dropna().sample(15, random_state=1).to_string())