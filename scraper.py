import os
import json
import time
import urllib.parse
import feedparser
import newspaper
from newspaper import Article
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from datetime import datetime, timezone, timedelta
import calendar

# ==========================================
# CONFIGURATION
# ==========================================
MAX_ARTICLES_PER_DAY = 10
MIN_RATING_THRESHOLD = 8

FEEDS = [
    # --- India-Focused Feeds (Priority) ---
    'https://www.bing.com/news/search?q=Healthcare+News+India&format=rss',
    'https://www.bing.com/news/search?q=PMJAY+OR+Ayushman+Bharat&format=rss',
    'https://www.bing.com/news/search?q=Indian+Hospitals+Doctors&format=rss',
    'https://www.bing.com/news/search?q=AI+in+Indian+Healthcare&format=rss',
    'https://www.bing.com/news/search?q=Ministry+of+Health+India&format=rss',
    
    # --- Global / International Feeds ---
    'https://www.bing.com/news/search?q=Global+Healthcare+Innovation&format=rss',
    'https://www.bing.com/news/search?q=Healthcare+AI+Worldwide&format=rss',
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
    # Using gemini-3.1-flash-lite as requested
    model = genai.GenerativeModel('gemini-3.1-flash-lite')

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
    
    now_utc = datetime.now(timezone.utc)
    cutoff_time = now_utc - timedelta(hours=24)
    
    # 1. Fetch URLs from all feeds
    print("Fetching RSS feeds...")
    article_data = {}
    for feed_url in FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:50]: # Top 50 from each feed
            link = entry.link
            pub_parsed = entry.get('published_parsed')
            
            # Filter by date if publication date is available in feed
            if pub_parsed:
                try:
                    pub_time = datetime.fromtimestamp(calendar.timegm(pub_parsed), tz=timezone.utc)
                    if pub_time < cutoff_time:
                        # Skip if older than 24 hours
                        continue
                except Exception as ex:
                    print(f"Error parsing pub_parsed for {link}: {ex}")
            
            if link not in article_data:
                article_data[link] = {
                    'pub_parsed': pub_parsed,
                    'news_image': entry.get('news_image')
                }
            
    article_links = list(article_data.keys())
    print(f"Found {len(article_links)} unique articles from the past 24 hours to process.")
    
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
            # Download and parse (Pretend to be a real web browser to avoid 403 Forbidden errors)
            config = newspaper.Config()
            config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            article = Article(url, config=config)
            article.download()
            article.parse()
            
            # Skip if missing crucial data (no longer strictly requiring top_image)
            if not article.title or not article.text:
                print(f"Skipping (Missing Content): {url}")
                continue
                
            # Filter by newspaper's publication date if available
            if article.publish_date:
                pub_date = article.publish_date
                try:
                    # Convert naive datetime to timezone-aware UTC, or normalize to UTC
                    if pub_date.tzinfo is None:
                        pub_date = pub_date.replace(tzinfo=timezone.utc)
                    else:
                        pub_date = pub_date.astimezone(timezone.utc)
                        
                    if pub_date < cutoff_time:
                        print(f"Skipping (Article too old: {pub_date}): {url}")
                        continue
                except Exception as e:
                    print(f"Error checking publish_date for {url}: {e}")
                
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
                
                # Retrieve direct image from feed or scrape from article
                feed_image = article_data[url].get('news_image')
                image_url = ""
                if feed_image:
                    image_url = feed_image
                elif article.top_image:
                    image_url = article.top_image
                elif hasattr(article, 'images') and article.images:
                    # Clean and find a good image from the article
                    valid_images = []
                    for img_url in article.images:
                        lower_url = img_url.lower()
                        # Skip small tracking pixels, logos, icons, avatars, sprites, etc.
                        if any(x in lower_url for x in ['logo', 'icon', 'ad', 'pixel', 'avatar', 'sprite']):
                            continue
                        if lower_url.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                            valid_images.append(img_url)
                    
                    if valid_images:
                        image_url = valid_images[0]
                    else:
                        image_url = list(article.images)[0]
                
                # Fallback to high-quality stock illustration if no image was found
                if not image_url:
                    image_url = "https://images.unsplash.com/photo-1505751172876-fa1923c5c528?w=800&auto=format&fit=crop"
                
                # Wrap non-Unsplash images with the global Cloudflare CDN-backed image proxy
                # This compresses them to WebP, limits width to 800px, bypasses hotlink blocks, and loads instantly.
                if image_url and not image_url.startswith("https://images.unsplash.com") and not "images.weserv.nl" in image_url:
                    try:
                        clean_url = image_url
                        if clean_url.startswith("http://"):
                            clean_url = clean_url[7:]
                        elif clean_url.startswith("https://"):
                            clean_url = clean_url[8:]
                        
                        fallback_url_encoded = urllib.parse.quote("https://images.unsplash.com/photo-1505751172876-fa1923c5c528?w=800")
                        image_url = f"https://images.weserv.nl/?url={urllib.parse.quote(clean_url)}&w=800&output=webp&errorredirect={fallback_url_encoded}"
                    except Exception as e:
                        print(f"Error proxying image URL: {e}")
                
                doc_data = {
                    'title': article.title,
                    'summary': summary,
                    'imageUrl': image_url,
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
