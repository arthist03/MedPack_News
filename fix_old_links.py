"""
One-time migration script to DEACTIVATE fake/generated articles in Firestore.

These are articles that were created by the old fallback system and have
non-genuine links (dashboard.pmjay.gov.in, news.google.com/search, scholar.google.com/scholar).

Sets isActive = false so they no longer appear in the app.

Usage:
  Set FIREBASE_SERVICE_ACCOUNT_KEY env var, then run:
  python fix_old_links.py
"""

import os
import json
import firebase_admin
from firebase_admin import credentials, firestore


# Links that indicate a fake/generated article (not a real scraped source)
FAKE_LINK_PATTERNS = [
    "https://dashboard.pmjay.gov.in/",
    "https://news.google.com/search",
    "https://scholar.google.com/scholar",
]


def main():
    # Setup Firebase
    fb_creds_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_KEY")
    if not fb_creds_json:
        raise ValueError("FIREBASE_SERVICE_ACCOUNT_KEY environment variable is missing!")

    cred_dict = json.loads(fb_creds_json)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    newsletters_ref = db.collection("newsletters")

    # Get ALL active newsletters
    active_docs = newsletters_ref.where("isActive", "==", True).get()

    print(f"Found {len(active_docs)} active articles. Checking for fake links...\n")

    deactivated = 0
    for doc in active_docs:
        data = doc.to_dict()
        link = data.get("readMoreLink", "")
        title = data.get("title", "(no title)")
        category = data.get("category", "?")

        # Check if this article has a fake/generated link
        is_fake = any(link.startswith(pattern) for pattern in FAKE_LINK_PATTERNS)

        if is_fake:
            print(f"  DEACTIVATING [{category:>7}] {title}")
            print(f"               Link: {link}")
            doc.reference.update({"isActive": False})
            deactivated += 1

    print(f"\nDone! Deactivated {deactivated} fake articles.")
    print(f"Remaining active articles: {len(active_docs) - deactivated}")


if __name__ == "__main__":
    main()
