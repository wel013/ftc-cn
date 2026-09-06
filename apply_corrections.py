import requests
import json
import os
import re
import time

# ── Config ────────────────────────────────────────────────
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
BITABLE_APP_TOKEN = os.environ.get("BITABLE_APP_TOKEN")
BITABLE_TABLE_ID = os.environ.get("BITABLE_TABLE_ID")
FTC_JSON_PATH = "ftc_teams.json"

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
        is_applied = fields.get("applied", False)
        if is_approved and not is_applied:
            approved.append({
                "record_id":   r["record_id"],
                "team_number": str(fields.get("team_number", "")).strip(),
                "city":        str(fields.get("city", "")).strip(),
                "state":       str(fields.get("state", "")).strip(),
                "country":     str(fields.get("country", "")).strip(),
                "name_full":   str(fields.get("name_full", "")).strip(),
                "name_short":  str(fields.get("name_short", "")).strip(),
            })
    return approved

# ── Step 3: Detect Chinese characters ─────────────────────


def has_chinese(text):
    return bool(re.search(r'[\u4e00-\u9fff]', text or ""))

# ── Step 4: Translate Chinese → English via Google ────────


def translate_to_english(text):
    if not text or not has_chinese(text):
        return text
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "zh-CN",
            "tl": "en",
            "dt": "t",
            "q": text,
        }
        res = requests.get(url, params=params, timeout=5)
        translated = res.json()[0][0][0]
        print(f"  Translated '{text}' → '{translated}'")
        return translated
    except Exception as e:
        print(f"  Translation failed for '{text}': {e}")
        return text

# ── Step 5: Geocode via Nominatim ─────────────────────────


def geocode(city, state, country):
    parts = [p for p in [city, state, country] if p]
    query = ", ".join(parts)
    if not query:
        return None, None

    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "limit": 1}
    headers = {"User-Agent": "ftc-map-correction/1.0"}

    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        results = res.json()
        if results:
            lat = float(results[0]["lat"])
            lng = float(results[0]["lon"])
            print(f"  Geocoded '{query}' → ({lat}, {lng})")
            return lat, lng
        else:
            print(f"  No geocode result for '{query}'")
            return None, None
    except Exception as e:
        print(f"  Geocoding failed: {e}")
        return None, None

# ── Step 6: Apply corrections to ftc_teams.json ───────────


def apply_corrections(rows):
    with open(FTC_JSON_PATH, "r", encoding="utf-8") as f:
        teams = json.load(f)

    updated = 0
    for row in rows:
        team_num = row["team_number"]

        # Translate any Chinese location fields to English
        city = translate_to_english(row["city"])
        state = translate_to_english(row["state"])
        country = translate_to_english(row["country"])
        name_full = row["name_full"]   # names stay as-is (no translation)
        name_short = row["name_short"]

        # Re-geocode if any location field was provided
        lat, lng = None, None
        if city or state or country:
            lat, lng = geocode(city, state, country)
            time.sleep(1)  # Nominatim rate limit

        for team in teams:
            if str(team.get("team_number", "")) == team_num:
                # Update location fields
                if city:
                    team["city"] = city
                if state:
                    team["state"] = state
                if country:
                    team["country"] = country

                # Update name fields
                if name_full:
                    team["nameFull"] = name_full
                if name_short:
                    team["nameShort"] = name_short

                # Update geocode_str if location changed
                if city or state or country:
                    team["geocode_str"] = ", ".join(
                        filter(None, [
                            team.get("city"),
                            team.get("state"),
                            team.get("country"),
                        ])
                    )

                # Update lat/lng if geocoding succeeded
                if lat is not None:
                    team["lat"] = lat
                    team["lng"] = lng
                    print(
                        f"✓ Updated team {team_num} — location ({lat}, {lng})")
                else:
                    print(
                        f"✓ Updated team {team_num} — text only (lat/lng unchanged)")

                updated += 1
                break
        else:
            print(f"✗ Team {team_num} not found — skipping")

    with open(FTC_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(teams, f, ensure_ascii=False, indent=2)

    print(f"\n{updated} team(s) updated.")
    return updated

# ── Step 7: Mark rows as applied in Feishu ────────────────


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
