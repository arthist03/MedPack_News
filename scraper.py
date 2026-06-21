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
    'https://www.bing.com/news/search?q=Global+Healthcare+News&format=rss',
    'https://www.bing.com/news/search?q=Healthcare+India&format=rss',
    'https://www.bing.com/news/search?q=Healthcare+AI+Worldwide&format=rss',
    'https://www.bing.com/news/search?q=PMJAY+OR+Ayushman+Bharat&format=rss',
    'https://www.bing.com/news/search?q=State+Healthcare+Packages+India&format=rss',
    'https://www.bing.com/news/search?q=AI+achievements+in+healthcare&format=rss',
    'https://www.bing.com/news/search?q=Achievements+of+doctors+and+hospitals&format=rss',
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
    # Using gemini-3.1-flash as requested
    model = genai.GenerativeModel('gemini-3.1-flash')

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

    Return ONLY a JSON object with exactly these two keys:
    "rating": an integer between 1 and 10
    "summary": the 2 sentence summary string
    """

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        data = json.loads(response.text)
        
        rating = int(data.get("rating", 0))
        summary = str(data.get("summary", "")).strip()
                
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
                print(f"Skipping (Missing Content): {url}")
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
