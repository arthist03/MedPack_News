import os
import json
import time
import feedparser
import newspaper
from newspaper import Article
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from datetime import datetime

# ==========================================
# CONFIGURATION
# ==========================================
MAX_ARTICLES_PER_DAY = 5
MIN_RATING_THRESHOLD = 8

FEEDS = [
    'https://news.google.com/rss/search?q=Global+Healthcare+News',
    'https://news.google.com/rss/search?q=Healthcare+India',
    'https://news.google.com/rss/search?q=Healthcare+AI+Worldwide',
    'https://news.google.com/rss/search?q=PMJAY+OR+Ayushman+Bharat',
    'https://news.google.com/rss/search?q=Maa+Yojana+OR+State+Healthcare+Packages',
    'https://news.google.com/rss/search?q=AI+achievements+in+healthcare',
    'https://news.google.com/rss/search?q=Achievements+of+doctors+and+hospitals',
]

# ==========================================
# SETUP FIREBASE & GEMINI
# ==========================================
def setup_clients():
    # Firebase
    fb_creds_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY')
    if not fb_creds_json:
        raise ValueError("FIREBASE_SERVICE_ACCOUNT_KEY environment variable is missing!")
    
    cred_dict = json.loads(fb_creds_json)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    # Gemini
    gemini_key = os.environ.get('GEMINI_API_KEY')
    if not gemini_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing!")
    
    genai.configure(api_key=gemini_key)
    # Using gemini-1.5-flash as it is free, fast, and highly capable
    model = genai.GenerativeModel('gemini-1.5-flash')

    return db, model

# ==========================================
# AI RATING & SUMMARY GENERATION
# ==========================================
def analyze_article_with_ai(model, title, text):
    prompt = f"""
    You are an expert healthcare editor for a premium app used by doctors and patients in India (PMJAY, Maa Yojana, etc).
    Review the following news article. 

    1. Rate it from 1 to 10 based on its "wow-factor", importance, and relevance to healthcare professionals, AI in healthcare, or PMJAY beneficiaries. (Generic or boring news should be rated 3 or below).
    2. Write a highly engaging, professional 2-sentence summary of the article. Do not sound like an AI. Make it sound like a premium news snippet.

    Title: {title}
    Text: {text[:3000]} # Truncated for context

    Format your response EXACTLY like this:
    [RATING] (just the integer)
    [SUMMARY] (the 2 sentence summary)
    """

    try:
        response = model.generate_content(prompt)
        content = response.text.strip().split('\n')
        
        rating = 0
        summary = ""
        
        for line in content:
            line = line.strip()
            if not line: continue
            if rating == 0 and line.isdigit():
                rating = int(line)
            elif not summary:
                summary = line
                
        return rating, summary
    except Exception as e:
        print(f"AI Error: {e}")
        return 0, ""

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    print(f"[{datetime.now()}] Starting Healthcare News Scraper Pipeline...")
    
    db, model = setup_clients()
    newsletters_ref = db.collection('newsletters')
    
    # 1. Fetch URLs from all feeds
    print("Fetching RSS feeds...")
    article_links = []
    for feed_url in FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:15]: # Top 15 from each feed
            article_links.append(entry.link)
            
    # Remove duplicates
    article_links = list(set(article_links))
    print(f"Found {len(article_links)} unique articles to process.")
    
    uploaded_count = 0
    
    # 2. Process articles
    for url in article_links:
        if uploaded_count >= MAX_ARTICLES_PER_DAY:
            print(f"Reached daily limit of {MAX_ARTICLES_PER_DAY} articles. Stopping.")
            break
            
        # Check if already exists in Firestore by URL
        existing_url = newsletters_ref.where('readMoreLink', '==', url).limit(1).get()
        if len(existing_url) > 0:
            continue
            
        try:
            # Download and parse
            article = Article(url)
            article.download()
            article.parse()
            
            # Skip if missing crucial data
            if not article.title or not article.text or not article.top_image:
                continue
                
            # Check if already exists in Firestore by Title (to catch different URLs of the same story)
            existing_title = newsletters_ref.where('title', '==', article.title).limit(1).get()
            if len(existing_title) > 0:
                print(f"Skipping duplicate title: {article.title}")
                continue
                
            print(f"Analyzing: {article.title}")
            
            # 3. AI Filter
            rating, summary = analyze_article_with_ai(model, article.title, article.text)
            print(f" -> Rating: {rating}/10")
            
            if rating >= MIN_RATING_THRESHOLD and summary:
                print(" -> ACCEPTED! Uploading to Firestore...")
                
                doc_data = {
                    'title': article.title,
                    'summary': summary,
                    'imageUrl': article.top_image,
                    'readMoreLink': url,
                    'isActive': True,
                    'createdAt': firestore.SERVER_TIMESTAMP
                }
                
                newsletters_ref.add(doc_data)
                uploaded_count += 1
                
        except Exception as e:
            print(f"Error processing {url}: {e}")
            
        # Small delay to respect rate limits
        time.sleep(2)
        
    print(f"[{datetime.now()}] Pipeline finished. Successfully uploaded {uploaded_count} premium articles.")

if __name__ == "__main__":
    main()
