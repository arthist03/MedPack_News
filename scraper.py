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
MIN_RATING_THRESHOLD = 8

INDIAN_FEEDS = [
    'https://www.bing.com/news/search?q=Healthcare+News+India&format=rss',
    'https://www.bing.com/news/search?q=PMJAY+OR+Ayushman+Bharat&format=rss',
    'https://www.bing.com/news/search?q=Indian+Hospitals+Doctors&format=rss',
    'https://www.bing.com/news/search?q=Ministry+of+Health+India&format=rss',
]

GLOBAL_FEEDS = [
    'https://www.bing.com/news/search?q=Global+Healthcare+Innovation&format=rss',
    'https://www.bing.com/news/search?q=Healthcare+AI+Worldwide&format=rss',
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
def analyze_article_with_ai(model, title, text, default_category):
    prompt = f"""
    You are an expert healthcare editor for a premium app used by doctors and patients in India (PMJAY, Maa Yojana, etc).
    Review the following news article. 

    1. Rate it from 1 to 10 based on its "wow-factor", importance, and relevance to healthcare professionals, AI in healthcare, or PMJAY beneficiaries. (Generic or boring news should be rated 3 or below).
    2. Write a highly engaging, professional 2-sentence summary of the article. Do not sound like an AI. Make it sound like a premium news snippet.
    3. Categorize this article into exactly one of these four categories:
       - "indian": General healthcare news, policies, government schemes (PMJAY, Ayushman Bharat), or doctor/hospital updates in India.
       - "global": General healthcare news, trends, policies, or hospital updates outside India.
       - "startup": News about healthcare startups, medical technology/device innovations, research institutes (like IITs, AIIMS, universities) and what they are researching, biotechnology, AI/ML in medicine, robotics, precision/personalized medicine, telemedicine, IoMT, digital twins, 3D bioprinting, or blockchain in healthcare.
       - "tip": Health, diet, wellness, exercise, or preventive care tips for patients or doctors.
       
       Note: If the article is about startups, new medical tech, research breakthroughs, AI, or advanced tech in medicine (Indian or global), prioritize placing it in the "startup" category.
       Default category if unclear: "{default_category}"

    Title: {title}
    Text: {text[:3000]} # Truncated for context

    Return ONLY a JSON object with exactly these three keys:
    "rating": an integer between 1 to 10
    "summary": the 2 sentence summary string
    "category": the category string ("indian", "global", "startup", or "tip")
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
        if category not in ["indian", "global", "startup", "tip"]:
            category = default_category
                
        return rating, summary, category
    except Exception as e:
        print(f"AI Error: {e}")
        return 0, "", default_category

# ==========================================
# FALLBACK GENERATOR (PLAN C)
# ==========================================
IMAGE_MAP = {
    'pmjay': 'https://images.unsplash.com/photo-1576091160550-2173dba999ef?w=800&auto=format&fit=crop',
    'scheme': 'https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?w=800&auto=format&fit=crop',
    'hospital': 'https://images.unsplash.com/photo-1586773860418-d3b3a998fc65?w=800&auto=format&fit=crop',
    'doctor': 'https://images.unsplash.com/photo-1622253692010-333f2da6031d?w=800&auto=format&fit=crop',
    'nurse': 'https://images.unsplash.com/photo-1584515979956-d9f6e5d09982?w=800&auto=format&fit=crop',
    'medicine': 'https://images.unsplash.com/photo-1584017911766-d451b3d0e843?w=800&auto=format&fit=crop',
    'health': 'https://images.unsplash.com/photo-1506126613408-eca07ce68773?w=800&auto=format&fit=crop',
    'diet': 'https://images.unsplash.com/photo-1490645935967-10de6ba17061?w=800&auto=format&fit=crop',
    'fitness': 'https://images.unsplash.com/photo-1517838277536-f5f99be501cd?w=800&auto=format&fit=crop',
    'ai': 'https://images.unsplash.com/photo-1507146426996-ef05306b995a?w=800&auto=format&fit=crop',
    'generic': 'https://images.unsplash.com/photo-1505751172876-fa1923c5c528?w=800&auto=format&fit=crop'
}

def get_fallback_image(keyword):
    keyword = keyword.lower()
    for key, url in IMAGE_MAP.items():
        if key in keyword:
            return url
    return IMAGE_MAP['generic']

def generate_educational_tip(model):
    prompt = """
    You are an expert healthcare editor for a premium app used by doctors and patients in India (PMJAY, Maa Yojana, etc).
    Since there is no breaking news today, generate an educational tip, scheme fact, or health guide card for our users.
    
    Choose one of these categories:
    1. A PMJAY / Ayushman Bharat / Maa Yojana scheme benefit or rule that people often don't know (e.g. pre-existing conditions covered from day 1, free diagnostics, how to check eligibility, card generation, claim process, hospital networks).
    2. A crucial daily health or wellness tip (diet, exercise, preventive care, hydration, hygiene, mental health).
    3. An advancement in AI or digital health in India (ABHA health ID, e-Sanjeevani teleconsultation).
    
    Make the title extremely catchy, short, and professional.
    Write a highly engaging, professional 2-sentence explanation/summary.
    Also, choose a relevant English search keyword for a medical/lifestyle image (choose exactly one of these: "pmjay", "scheme", "hospital", "doctor", "nurse", "medicine", "health", "diet", "fitness", "ai").
    
    Return ONLY a JSON object with exactly these three keys:
    "title": a short catchy title string
    "summary": the 2 sentence summary/explanation string
    "image_keyword": the selected keyword string
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        data = json.loads(response.text)
        
        title = str(data.get("title", "")).strip()
        summary = str(data.get("summary", "")).strip()
        keyword = str(data.get("image_keyword", "generic")).strip().lower()
        
        return title, summary, keyword
    except Exception as e:
        print(f"Fallback Generator Error: {e}")
        return "", "", "generic"

def generate_fallback_article_for_category(model, category):
    if category == 'indian':
        topic_desc = "a major Indian healthcare initiative, PMJAY / Ayushman Bharat / Maa Yojana benefit/policy update, public health project, or AIIMS/government hospital development in India."
    elif category == 'global':
        topic_desc = "a significant global medical trend, breakthrough clinical study, WHO healthcare update, or major international wellness policy."
    elif category == 'startup':
        topic_desc = "a medical technology innovation, a healthcare startup milestone, AI/ML application in diagnostics, robotic surgery advancements, or university/IIT health tech research."
    else:  # 'tip'
        topic_desc = "a crucial daily health, diet, wellness, preventative care, or medical tip for patients and doctors."

    prompt = f"""
    You are an expert healthcare editor for a premium app used by doctors and patients in India (PMJAY, Maa Yojana, etc).
    Generate a high-quality, engaging healthcare news snippet or educational article for the "{category}" category.
    The article must cover: {topic_desc}

    Make the title extremely catchy, short, and professional.
    Write a highly engaging, professional 2-sentence summary/explanation of this topic.
    Choose a relevant English search keyword for a medical/lifestyle image (choose exactly one of these: "pmjay", "scheme", "hospital", "doctor", "nurse", "medicine", "health", "diet", "fitness", "ai").

    Return ONLY a JSON object with exactly these three keys:
    "title": a short catchy title string
    "summary": the 2 sentence summary string
    "image_keyword": the selected keyword string
    """
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        data = json.loads(response.text)
        title = str(data.get("title", "")).strip()
        summary = str(data.get("summary", "")).strip()
        keyword = str(data.get("image_keyword", "generic")).strip().lower()
        return title, summary, keyword
    except Exception as e:
        print(f"Failed to generate fallback for {category}: {e}")
        return "", "", "generic"

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
                    'news_image': entry.get('news_image'),
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
                    'news_image': entry.get('news_image'),
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
                    'news_image': entry.get('news_image'),
                    'category': 'startup'
                }
            
    article_links = list(article_data.keys())
    print(f"Found {len(article_links)} unique articles from the past 24 hours to process.")
    
    uploaded_by_category = { 'indian': 0, 'global': 0, 'startup': 0, 'tip': 0 }
    TARGET_ARTICLES_PER_CATEGORY = 4
    MAX_ARTICLES_PER_CATEGORY = 6
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
            rating, summary, category = analyze_article_with_ai(model, article.title, article.text, article_data[url]['category'])
            print(f" -> Rating: {rating}/10, Category: {category}")
            
            if rating >= MIN_RATING_THRESHOLD and summary:
                if uploaded_by_category[category] >= MAX_ARTICLES_PER_CATEGORY:
                    print(f" -> Category '{category}' has already reached its cap of {MAX_ARTICLES_PER_CATEGORY}. Skipping upload.")
                    continue
                
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
                    'category': category,
                    'isActive': True,
                    'createdAt': firestore.SERVER_TIMESTAMP
                }
                
                newsletters_ref.add(doc_data)
                uploaded_by_category[category] += 1
                uploaded_count += 1
                
        except Exception as e:
            print(f"Error processing {url}: {e}")
            
        # Small delay to respect rate limits
        time.sleep(2)
        
    # 3. Fill gaps for categories that have fewer than 4 articles
    print("\nChecking for category gaps (Target: at least 4 articles per category)...")
    for cat in ['indian', 'global', 'startup', 'tip']:
        current_count = uploaded_by_category[cat]
        gap = TARGET_ARTICLES_PER_CATEGORY - current_count
        if gap > 0:
            print(f"Category '{cat}' only has {current_count} articles. Generating {gap} fallback articles...")
            retries = 0
            while gap > 0 and retries < gap * 3:
                retries += 1
                title, summary, keyword = generate_fallback_article_for_category(model, cat)
                if not title or not summary:
                    continue
                
                # Check duplicate title in Firestore
                existing_title = newsletters_ref.where('title', '==', title).limit(1).get()
                if len(existing_title) > 0:
                    print(f"Skipping duplicate fallback title: {title}")
                    continue
                
                image_url = get_fallback_image(keyword)
                
                # Wrap with CDN resize proxy
                try:
                    clean_url = image_url
                    if clean_url.startswith("http://"):
                        clean_url = clean_url[7:]
                    elif clean_url.startswith("https://"):
                        clean_url = clean_url[8:]
                    fallback_url_encoded = urllib.parse.quote("https://images.unsplash.com/photo-1505751172876-fa1923c5c528?w=800")
                    image_url = f"https://images.weserv.nl/?url={urllib.parse.quote(clean_url)}&w=800&output=webp&errorredirect={fallback_url_encoded}"
                except Exception as e:
                    print(f"Error proxying fallback image: {e}")
                
                doc_data = {
                    'title': title,
                    'summary': summary,
                    'imageUrl': image_url,
                    'readMoreLink': 'https://dashboard.pmjay.gov.in/', # General fallback link
                    'category': cat,
                    'isActive': True,
                    'createdAt': firestore.SERVER_TIMESTAMP
                }
                
                newsletters_ref.add(doc_data)
                print(f"Uploaded fallback educational card for '{cat}': '{title}'")
                uploaded_by_category[cat] += 1
                uploaded_count += 1
                gap -= 1
                time.sleep(1)
        else:
            print(f"Category '{cat}' is fully satisfied with {current_count} articles.")
            
    print(f"[{datetime.now()}] Pipeline finished. Successfully uploaded {uploaded_count} premium articles.")

if __name__ == "__main__":
    main()
