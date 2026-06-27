"""
One-time migration script to fix existing Firestore newsletters
that still have 'https://dashboard.pmjay.gov.in/' as their readMoreLink.

Replaces them with genuine search URLs:
  - indian/global/startup -> Google News search
  - tip -> Google Scholar search

Usage:
  Set FIREBASE_SERVICE_ACCOUNT_KEY env var, then run:
  python fix_old_links.py
"""

import os
import json
import urllib.parse
import firebase_admin
from firebase_admin import credentials, firestore


def build_search_url(category, title):
    """Build a genuine search URL from the article's title and category."""
    # Clean the title: take first ~6 meaningful words for a focused search query
    words = title.split()
    query = " ".join(words[:6])
    encoded = urllib.parse.quote_plus(query)
    
    if category == "tip":
        return f"https://scholar.google.com/scholar?q={encoded}"
    else:
        return f"https://news.google.com/search?q={encoded}"


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

    # Query all documents with the old hardcoded link
    old_link = "https://dashboard.pmjay.gov.in/"
    docs = newsletters_ref.where("readMoreLink", "==", old_link).get()

    print(f"Found {len(docs)} articles with the old dashboard link.\n")

    if len(docs) == 0:
        print("Nothing to fix! All articles already have genuine links.")
        return

    updated = 0
    for doc in docs:
        data = doc.to_dict()
        title = data.get("title", "")
        category = data.get("category", "indian")

        new_link = build_search_url(category, title)

        print(f"  [{category.upper():>7}] {title}")
        print(f"           -> {new_link}")

        # Update the document
        doc.reference.update({"readMoreLink": new_link})
        updated += 1

    print(f"\nDone! Updated {updated} articles with genuine source links.")


if __name__ == "__main__":
    main()
