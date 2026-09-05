import requests
import json
import os

# ── Config ────────────────────────────────────────────────
FEISHU_APP_ID     = os.environ.get("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
BITABLE_APP_TOKEN = os.environ.get("BITABLE_APP_TOKEN")  # from URL: /base/XXXXXX
BITABLE_TABLE_ID  = os.environ.get("BITABLE_TABLE_ID")   # from URL: ?table=XXXXXX
FTC_JSON_PATH     = "ftc_teams.json"

# ── Step 1: Get Feishu access token ───────────────────────
def get_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    res = requests.post(url, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    })
    return res.json()["tenant_access_token"]

# ── Step 2: Read approved + not yet applied rows ───────────
def get_approved_rows(token):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(url, headers=headers)
    records = res.json().get("data", {}).get("items", [])

    approved = []
    for r in records:
        fields = r.get("fields", {})
        is_approved = fields.get("approved", False)
        is_applied  = fields.get("applied", False)
        if is_approved and not is_applied:
            approved.append({
                "record_id":   r["record_id"],
                "team_number": str(fields.get("team_number", "")).strip(),
                "city":        str(fields.get("city", "")).strip(),
                "state":       str(fields.get("state", "")).strip(),
                "country":     str(fields.get("country", "")).strip(),
            })
    return approved

# ── Step 3: Apply corrections to ftc_teams.json ───────────
def apply_corrections(rows):
    with open(FTC_JSON_PATH, "r", encoding="utf-8") as f:
        teams = json.load(f)

    updated = 0
    for row in rows:
        team_num = row["team_number"]
        for team in teams:
            if str(team.get("team_number", "")) == team_num:
                if row["city"]:    team["city"]    = row["city"]
                if row["state"]:   team["state"]   = row["state"]
                if row["country"]: team["country"] = row["country"]
                updated += 1
                print(f"✓ Updated team {team_num}")
                break
        else:
            print(f"✗ Team {team_num} not found — skipping")

    with open(FTC_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(teams, f, ensure_ascii=False, indent=2)

    print(f"\n{updated} team(s) updated.")
    return updated

# ── Step 4: Mark rows as applied ──────────────────────────
def mark_applied(token, record_ids):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    for rid in record_ids:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records/{rid}"
        requests.put(url, headers=headers, json={"fields": {"applied": True}})
        print(f"Marked {rid} as applied")

# ── Main ──────────────────────────────────────────────────
if __name__ == "__main__":
    print("Getting Feishu access token...")
    token = get_access_token()

    print("Fetching approved corrections...")
    rows = get_approved_rows(token)
    print(f"Found {len(rows)} approved correction(s)")

    if not rows:
        print("Nothing to apply.")
    else:
        apply_corrections(rows)
        mark_applied(token, [r["record_id"] for r in rows])
        print("Done!")