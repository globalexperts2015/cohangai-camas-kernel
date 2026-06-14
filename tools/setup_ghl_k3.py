"""Create Breakout Challenge K3 custom fields in GHL.

The command is idempotent and prints the JSON value required for
GHL_K3_CUSTOM_FIELD_IDS.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


BASE_URL = "https://services.leadconnectorhq.com"
FIELDS = {
    "k3_resume_url": ("Breakout K3 Resume URL", "TEXT"),
    "k3_current_day": ("Breakout K3 Current Day", "NUMERICAL"),
    "k3_opportunity_score": ("Breakout K3 Opportunity Score", "NUMERICAL"),
    "k3_evidence_status": ("Breakout K3 Evidence Status", "TEXT"),
    "k3_offer_readiness": ("Breakout K3 Offer Readiness", "TEXT"),
    "k3_last_active_at": ("Breakout K3 Last Active At", "TEXT"),
}


def main() -> int:
    workspace = Path(__file__).resolve().parents[4]
    load_dotenv(workspace / "cohangai/.env", override=False)
    api_key = os.getenv("GHL_API_KEY", "")
    location_id = os.getenv("GHL_LOCATION_ID", "")
    if not api_key or not location_id:
        print("GHL_API_KEY and GHL_LOCATION_ID are required")
        return 1

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": "2021-07-28",
        "Content-Type": "application/json",
    }
    mapping: dict[str, str] = {}
    with httpx.Client(headers=headers, timeout=30) as client:
        response = client.get(f"{BASE_URL}/locations/{location_id}/customFields")
        response.raise_for_status()
        existing = response.json().get("customFields", [])
        by_name = {
            (field.get("name") or "").strip().lower(): field
            for field in existing
        }

        for key, (name, data_type) in FIELDS.items():
            field = by_name.get(name.lower())
            if not field:
                response = client.post(
                    f"{BASE_URL}/locations/{location_id}/customFields",
                    json={
                        "name": name,
                        "dataType": data_type,
                        "placeholder": name,
                        "model": "contact",
                    },
                )
                if response.status_code == 400:
                    existing_id = (response.json().get("meta") or {}).get("existingId")
                    if existing_id:
                        field = {"id": existing_id}
                if field is None:
                    response.raise_for_status()
                    field = response.json().get("customField") or response.json()
            field_id = field.get("id")
            if not field_id:
                raise RuntimeError(f"Custom field {name} has no id")
            mapping[key] = field_id

    print(json.dumps(mapping, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
