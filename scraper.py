import os
import json
import re
import time
import urllib.parse
import requests
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
MIN_RATING_THRESHOLD = 6

INDIAN_FEEDS = [
    'https://www.bing.com/news/search?q=Healthcare+News+India&format=rss',
    'https://www.bing.com/news/search?q=PMJAY+OR+Ayushman+Bharat&format=rss',
    'https://www.bing.com/news/search?q=Indian+Hospitals+Doctors&format=rss',
    'https://www.bing.com/news/search?q=Ministry+of+Health+India&format=rss',
    'https://www.bing.com/news/search?q=AIIMS+Hospital+India+News&format=rss',
    'https://www.bing.com/news/search?q=India+Public+Health+Policy&format=rss',
    'https://www.bing.com/news/search?q=National+Health+Mission+India&format=rss',
    'https://www.bing.com/news/search?q=Indian+Medical+Association+News&format=rss',
]

GLOBAL_FEEDS = [
    'https://www.bing.com/news/search?q=Global+Healthcare+Innovation&format=rss',
    'https://www.bing.com/news/search?q=Healthcare+AI+Worldwide&format=rss',
    'https://www.bing.com/news/search?q=WHO+Health+News&format=rss',
    'https://www.bing.com/news/search?q=Global+Medical+Breakthrough&format=rss',
    'https://www.bing.com/news/search?q=International+Hospital+News&format=rss',
    'https://www.bing.com/news/search?q=CDC+Public+Health+Update&format=rss',
    'https://www.bing.com/news/search?q=Global+Vaccine+Drug+Approval&format=rss',
]

TECH_AND_STARTUP_FEEDS = [
    'https://www.bing.com/news/search?q=Healthcare+Startups+MedTech&format=rss',
    'https://www.bing.com/news/search?q=AI+Machine+Learning+Healthcare&format=rss',
    'https://www.bing.com/news/search?q=Robotics+Automation+Healthcare&format=rss',
    'https://www.bing.com/news/search?q=Precision+Personalized+Medicine&format=rss',
    'https://www.bing.com/news/search?q=Telemedicine+Virtual+Hospital&format=rss',
    'https://www.bing.com/news/search?q=Internet+of+Medical+Things+IoMT&format=rss',
    'https://www.bing.com/news/search?q=Digital+Twins+Healthcare&format=rss',
    'https://www.bing.com/news/search?q=Biotechnology+Advanced+Therapeutics&format=rss',
    'https://www.bing.com/news/search?q=3D+Bioprinting+Healthcare&format=rss',
    'https://www.bing.com/news/search?q=Blockchain+Healthcare+Security&format=rss',
    'https://www.bing.com/news/search?q=Healthcare+Research+Institutes&format=rss',
    'https://www.bing.com/news/search?q=HealthTech+Funding+Investment&format=rss',
    'https://www.bing.com/news/search?q=Digital+Health+Wearables+News&format=rss',
]

RESEARCH_FEEDS = [
    'https://www.nature.com/nm.rss',
    'https://jamanetwork.com/rss/journals/jama/mostread.xml',
    'https://connect.medrxiv.org/medrxiv_xml.php?subject=public_health',
    'https://connect.medrxiv.org/medrxiv_xml.php?subject=primary_care',
    'https://www.bing.com/news/search?q=Health+Tips+Medical+Study+Findings&format=rss',
    'https://www.bing.com/news/search?q=Diet+Nutrition+Health+Research&format=rss',
    'https://www.bing.com/news/search?q=Exercise+Fitness+Health+Benefits+Study&format=rss',
    'https://www.bing.com/news/search?q=Mental+Health+Wellness+Research&format=rss',
    'https://www.bing.com/news/search?q=Medical+Research+Clinical+Trial+Results&format=rss',
    'https://www.bing.com/news/search?q=Preventive+Healthcare+Tips+Study&format=rss',
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
def analyze_article_with_ai(model, title, text, default_category, recent_titles):
    prompt = f"""
    You are an expert healthcare editor for a premium app used by doctors and patients in India (PMJAY, Maa Yojana, etc).
    Review the following news article or medical research paper/abstract. 

    1. Rate it from 1 to 10 based on its "wow-factor", importance, and relevance to healthcare professionals, AI in healthcare, or PMJAY beneficiaries. (Generic or boring news should be rated 3 or below).
    2. Write a highly engaging, professional 2-sentence summary of the article. 
       - CRITICAL TIP RULE: If the article is classified as a "tip" or is a research paper being summarized as a "tip", do NOT write an academic summary of the study methodology. Instead, extract a practical, actionable health, diet, wellness, or preventative care tip for patients/clinicians based directly on the paper's findings/conclusions.
       - Do not sound like an AI. Make it sound like a premium news snippet or a clean, helpful advice tip.
    3. Categorize this article into exactly one of these four categories:
       - "indian": General healthcare news, policies, government schemes (PMJAY, Ayushman Bharat), or doctor/hospital updates in India.
       - "global": General healthcare news, trends, policies, or hospital updates outside India.
       - "startup": News about healthcare startups, medical technology/device innovations, research institutes (like IITs, AIIMS, universities) and what they are researching, biotechnology, AI/ML in medicine, robotics, precision/personalized medicine, telemedicine, IoMT, digital twins, 3D bioprinting, or blockchain in healthcare.
       - "tip": Scientific medical studies, clinical trials, health, diet, wellness, exercise, or preventive care advice that translates into tips for patients or doctors.
       
       Note: If the article is a scientific study/clinical trial or explicitly offers healthy living/preventive advice, put it in the "tip" category. If it is about tech, AI, or corporate startups, prioritize "startup".
       Default category if unclear: "{default_category}"

    4. CRITICAL DEDUPLICATION CHECK: Compare this article's headline and topic against the list of recently published news titles below. If it covers the exact same event, announcement, development, or advice (even if written differently), you MUST identify it as a duplicate by setting the "rating" to 0 and "is_duplicate" to true.
       Recent titles list: {json.dumps(recent_titles)}

    Title: {title}
    Text: {text[:3000]} # Truncated for context

    Return ONLY a JSON object with exactly these four keys:
    "rating": an integer between 0 to 10 (use 0 if duplicate)
    "summary": the 2 sentence summary string
    "category": the category string ("indian", "global", "startup", or "tip")
    "is_duplicate": a boolean (true if it covers the same news event/announcement as any recent title, false otherwise)
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
        category = str(data.get("category", default_category)).strip().lower()
        is_duplicate = bool(data.get("is_duplicate", False))
        if category not in ["indian", "global", "startup", "tip"]:
            category = default_category
            
        if is_duplicate:
            rating = 0
                
        return rating, summary, category, is_duplicate
    except Exception as e:
        print(f"AI Error: {e}")
        return 0, "", default_category, False

# ==========================================
# IMAGE SEARCH (for articles without images)
# ==========================================
GENERIC_FALLBACK_IMAGE = "https://images.unsplash.com/photo-1505751172876-fa1923c5c528?w=1600&fm=webp&q=100&fit=crop"

def search_image_by_keywords(title):
    """Search Bing Images for a relevant image based on article title keywords.
    Returns the URL of the first matching image, or falls back to a generic stock photo.
    """
    # Take first ~5 words from the title + 'healthcare' for a focused image search
    words = title.split()[:5]
    query = " ".join(words) + " healthcare"
    search_url = f"https://www.bing.com/images/search?q={urllib.parse.quote_plus(query)}&first=1&qft=+filterui:photo-photo"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(search_url, headers=headers, timeout=10)
        if response.status_code == 200:
            # Bing embeds original image URLs in JSON data attributes as "murl"
            urls = re.findall(r'"murl":"(https?://[^"]+)"', response.text)
            if urls:
                # Return the first valid image URL found
                print(f"   Found relevant image via Bing for: {title[:50]}...")
                return urls[0]
    except Exception as e:
        print(f"   Image search failed for '{title[:40]}': {e}")
    
    print(f"   No image found via search, using generic fallback for: {title[:50]}...")
    return GENERIC_FALLBACK_IMAGE

def extract_image_from_feed_entry(entry):
    """Extract the best available image URL from an RSS feed entry."""
    # Check direct news_image field
    if entry.get('news_image'):
        return entry.get('news_image')
    
    # Check media:content (common in RSS feeds)
    if hasattr(entry, 'media_content') and entry.media_content:
        for media in entry.media_content:
            url = media.get('url', '')
            if url and any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', 'image']):
                return url
    
    # Check media:thumbnail
    if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
        for thumb in entry.media_thumbnail:
            url = thumb.get('url', '')
            if url:
                return url
    
    # Check enclosures
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href', '') or enc.get('url', '')
    
    # Check links for image types
    if hasattr(entry, 'links'):
        for link in entry.links:
            if link.get('type', '').startswith('image/'):
                return link.get('href', '')
    
    return ""
# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    print(f"[{datetime.now()}] Starting Healthcare News Scraper Pipeline...")
    
    db, model = setup_clients()
    newsletters_ref = db.collection('newsletters')
    
    # Retrieve recent active article titles from the last 7 days for semantic deduplication
    recent_titles = []
    try:
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent_docs = newsletters_ref.where('createdAt', '>=', seven_days_ago).get()
        for doc in recent_docs:
            d = doc.to_dict()
            title = d.get('title')
            if title:
                recent_titles.append(title.strip())
        print(f"Retrieved {len(recent_titles)} recent titles from the last 7 days for semantic deduplication.")
    except Exception as e:
        print(f"Error fetching recent titles from Firestore: {e}")
        
    now_utc = datetime.now(timezone.utc)
    cutoff_time = now_utc - timedelta(hours=24)
    
    # 1. Fetch URLs from all feeds
    print("Fetching RSS feeds...")
    article_data = {}
    # Process Indian Feeds
    for feed_url in INDIAN_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:50]:
            link = entry.link
            pub_parsed = entry.get('published_parsed')
            
            # Filter by date if publication date is available in feed
            if pub_parsed:
                try:
                    pub_time = datetime.fromtimestamp(calendar.timegm(pub_parsed), tz=timezone.utc)
                    if pub_time < cutoff_time:
                        continue
                except Exception as ex:
                    print(f"Error parsing pub_parsed for {link}: {ex}")
            
            if link not in article_data:
                article_data[link] = {
                    'pub_parsed': pub_parsed,
                    'feed_entry': entry,
                    'category': 'indian'
                }

    # Process Global Feeds
    for feed_url in GLOBAL_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:50]:
            link = entry.link
            pub_parsed = entry.get('published_parsed')
            
            # Filter by date if publication date is available in feed
            if pub_parsed:
                try:
                    pub_time = datetime.fromtimestamp(calendar.timegm(pub_parsed), tz=timezone.utc)
                    if pub_time < cutoff_time:
                        continue
                except Exception as ex:
                    print(f"Error parsing pub_parsed for {link}: {ex}")
            
            if link not in article_data:
                article_data[link] = {
                    'pub_parsed': pub_parsed,
                    'feed_entry': entry,
                    'category': 'global'
                }

    # Process Tech and Startup Feeds
    for feed_url in TECH_AND_STARTUP_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:50]:
            link = entry.link
            pub_parsed = entry.get('published_parsed')
            
            # Filter by date if publication date is available in feed
            if pub_parsed:
                try:
                    pub_time = datetime.fromtimestamp(calendar.timegm(pub_parsed), tz=timezone.utc)
                    if pub_time < cutoff_time:
                        continue
                except Exception as ex:
                    print(f"Error parsing pub_parsed for {link}: {ex}")
            
            if link not in article_data:
                article_data[link] = {
                    'pub_parsed': pub_parsed,
                    'feed_entry': entry,
                    'category': 'startup'
                }
            
    # Process Research Feeds (for daily health tips)
    for feed_url in RESEARCH_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:50]:
            link = entry.link
            pub_parsed = entry.get('published_parsed')
            
            # Filter by date if publication date is available in feed
            if pub_parsed:
                try:
                    pub_time = datetime.fromtimestamp(calendar.timegm(pub_parsed), tz=timezone.utc)
                    if pub_time < cutoff_time:
                        continue
                except Exception as ex:
                    print(f"Error parsing pub_parsed for {link}: {ex}")
            
            if link not in article_data:
                article_data[link] = {
                    'pub_parsed': pub_parsed,
                    'feed_entry': entry,
                    'category': 'tip'
                }
            
    article_links = list(article_data.keys())
    print(f"Found {len(article_links)} unique articles from the past 24 hours to process.")
    
    uploaded_by_category = { 'indian': 0, 'global': 0, 'startup': 0, 'tip': 0 }
    TARGET_ARTICLES_PER_CATEGORY = 10
    MAX_ARTICLES_PER_CATEGORY = 10
    uploaded_count = 0
    
    # 2. Process articles
    for url in article_links:
        # Check if all categories are already satisfied to MAX_ARTICLES_PER_CATEGORY
        if all(count >= MAX_ARTICLES_PER_CATEGORY for count in uploaded_by_category.values()):
            print("All categories have reached their daily limit. Stopping feed processing.")
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
            rating, summary, category, is_duplicate = analyze_article_with_ai(model, article.title, article.text, article_data[url]['category'], recent_titles)
            print(f" -> Rating: {rating}/10, Category: {category}, Duplicate: {is_duplicate}")
            
            if rating >= MIN_RATING_THRESHOLD and summary:
                if uploaded_by_category[category] >= MAX_ARTICLES_PER_CATEGORY:
                    print(f" -> Category '{category}' has already reached its cap of {MAX_ARTICLES_PER_CATEGORY}. Skipping upload.")
                    continue
                
                print(" -> ACCEPTED! Uploading to Firestore...")
                
                # Retrieve direct image from feed or scrape from article
                feed_image = extract_image_from_feed_entry(article_data[url].get('feed_entry', {}))
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
                
                # If no image found, search for a relevant one based on article title
                if not image_url:
                    image_url = search_image_by_keywords(article.title)
                
                # Wrap non-Unsplash images with the global Cloudflare CDN-backed image proxy
                # This compresses them to WebP, limits width to 1600px, bypasses hotlink blocks, and loads losslessly.
                if image_url and not image_url.startswith("https://images.unsplash.com") and not "images.weserv.nl" in image_url:
                    try:
                        clean_url = image_url
                        if clean_url.startswith("http://"):
                            clean_url = clean_url[7:]
                        elif clean_url.startswith("https://"):
                            clean_url = clean_url[8:]
                        
                        fallback_url_encoded = urllib.parse.quote("https://images.unsplash.com/photo-1505751172876-fa1923c5c528?w=1600&fm=webp&q=100")
                        image_url = f"https://images.weserv.nl/?url={urllib.parse.quote(clean_url)}&w=1600&q=100&output=webp&errorredirect={fallback_url_encoded}"
                    except Exception as e:
                        print(f"Error proxying image URL: {e}")
                
                doc_data = {
                    'title': article.title,
                    'summary': summary,
                    'imageUrl': image_url,
                    'readMoreLink': url,
                    'category': category,
                    'isActive': True,
                    'createdAt': firestore.SERVER_TIMESTAMP
                }
                
                newsletters_ref.add(doc_data)
                uploaded_by_category[category] += 1
                uploaded_count += 1
                recent_titles.append(article.title.strip())
                
        except Exception as e:
            print(f"Error processing {url}: {e}")
            
        # Small delay to respect rate limits
        time.sleep(2)
        
    # Print final summary
    print("\n" + "=" * 50)
    print("FINAL RESULTS (only real scraped articles):")
    for cat in ['indian', 'global', 'startup', 'tip']:
        print(f"  {cat}: {uploaded_by_category[cat]} articles")
    print(f"[{datetime.now()}] Pipeline finished. Successfully uploaded {uploaded_count} real articles.") 

if __name__ == "__main__":
    main()
