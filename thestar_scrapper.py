import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urljoin
from requests.exceptions import RequestException, Timeout
import os
from datetime import datetime
import re
from collections import defaultdict

# Global session for connection pooling
session = None

# Global tally for tracking articles per section
section_tally = defaultdict(int)

def initialize_session():
    """Initialize requests session with connection pooling and headers"""
    global session
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    })
    # Configure connection pooling
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=10,  # Number of connection pools to cache
        pool_maxsize=20,      # Maximum number of connections to save in the pool
        max_retries=3         # Retry failed requests
    )
    session.mount('http://', adapter)
    session.mount('https://', adapter)

def close_session():
    """Close the session to clean up connections"""
    global session
    if session:
        session.close()

def print_section_tallies():
    """Print current tally of articles per section"""
    print("\n" + "="*50)
    print("SECTION TALLIES")
    print("="*50)
    total = 0
    for section, count in sorted(section_tally.items()):
        print(f"{section:<25}: {count:>4} articles")
        total += count
    print("-"*50)
    print(f"{'TOTAL':<25}: {total:>4} articles")
    print("="*50 + "\n")

# Helper to parse date strings (The Star may not always provide, so keep flexible)
def parse_article_date(date_str):
    if not date_str:
        return None
    date_str = date_str.strip()
    # Remove ordinal suffixes (st, nd, rd, th)
    date_str = re.sub(r'(\d{1,2})(st|nd|rd|th)', r'\1', date_str)
    formats = [
        "%A %d %B, %Y %I:%M %p",
        "%A %d %B, %Y %I %p",
        "%A %d %B, %Y %H:%M",
        "%A %d %B, %Y",
        "%d %B %Y %I:%M %p",
        "%d %B %Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except Exception:
            continue
    print(f"[WARN] Could not parse date: '{date_str}'")
    return None

def save_articles(articles, filename='thestarkenya_articles.json'):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"Progress saved: {len(articles)} articles.")
    print_section_tallies()

def load_existing_articles(filename='thestarkenya_articles.json'):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            try:
                articles = json.load(f)
                # Rebuild section tally from existing articles
                for article in articles:
                    category = article.get('category', 'unknown')
                    section_tally[category] += 1
                return articles
            except Exception:
                return []
    return []

def scrape_homepage(articles, seen_urls, seen_titles):
    global session
    url = "https://www.the-star.co.ke/"
    print(f"Scraping homepage: {url}")
    
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            print(f"Failed to fetch homepage: {url}, status code: {resp.status_code}")
            return
    except Timeout:
        print(f"Timeout fetching homepage: {url}")
        save_articles(articles)
        return
    except RequestException as e:
        print(f"Request failed: {e}")
        save_articles(articles)
        return
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    # Find all <a> tags with <h3> or <h6> children (main and other news)
    for a in soup.find_all('a', href=True):
        h3 = a.find('h3', class_='line-clamp-3')
        h6 = a.find('h6', class_='font-sans')
        if h3 or h6:
            title = h3.get_text(strip=True) if h3 else h6.get_text(strip=True)
            href = a['href']
            if not href.startswith('http'):
                href = urljoin(url, href)
            title_key = title.strip().lower() if title else ''
            if href not in seen_urls and title_key and title_key not in seen_titles:
                # Try to guess category from URL
                parts = href.replace("https://www.the-star.co.ke/", "").split("/")
                category = parts[0] if len(parts) > 1 else "homepage"
                article_data = scrape_article_details(title, href, category)
                if article_data:
                    articles.append(article_data)
                    seen_urls.add(href)
                    seen_titles.add(title_key)
                    section_tally[category] += 1
                    print(f"  [Homepage] Added article: {href}")
                    if len(articles) % 20 == 0:
                        save_articles(articles)
                time.sleep(0.5)

def is_premium_content(soup):
    premium_tag = soup.find('h3', class_='text-primary')
    if premium_tag and 'premium content' in premium_tag.get_text(strip=True).lower():
        return True
    return False

def has_no_more_articles(soup):
    return soup.find('span', string=lambda s: s and 'no more articles' in s.lower()) is not None

def find_load_more_button(soup):
    return soup.find('button', string=lambda s: s and 'load more articles' in s.lower())

# Enhanced category scraping with Load More support and premium content skip
def scrape_category(category_url, category_name=None, max_pages=50):
    global session
    if category_name is None:
        category_name = category_url.split("/")[-1]
    
    articles = load_existing_articles()
    seen_urls = set(a['url'] for a in articles)
    seen_titles = set(a['title'].strip().lower() for a in articles if a.get('title'))
    visited_pages = set()
    
    url = category_url
    page_count = 0
    category_start_count = len(articles)
    
    print(f"\n--- Starting scrape for category: {category_name.upper()} ---")
    
    while url and url not in visited_pages and page_count < max_pages:
        print(f"Scraping page {page_count + 1}: {url}")
        visited_pages.add(url)
        
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                print(f"Failed to fetch page: {url}, status code: {resp.status_code}")
                break
        except Timeout:
            print(f"Timeout fetching page: {url}")
            save_articles(articles)
            break
        except RequestException as e:
            print(f"Request failed: {e}")
            save_articles(articles)
            break
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        if has_no_more_articles(soup):
            print("No more articles found on this page.")
            break
        
        # Find all <a> tags with <h3> or <h6> children
        page_articles_found = 0
        for a in soup.find_all('a', href=True):
            h3 = a.find('h3', class_='line-clamp-3') or a.find('h3', class_='underline-offset-2')
            h6 = a.find('h6', class_='font-sans')
            if h3 or h6:
                title = h3.get_text(strip=True) if h3 else h6.get_text(strip=True)
                href = a['href']
                if not href.startswith('http'):
                    href = urljoin(url, href)
                title_key = title.strip().lower() if title else ''
                if href not in seen_urls and title_key and title_key not in seen_titles:
                    # Fetch article and skip if premium
                    article_data = scrape_article_details(title, href, category_name)
                    if article_data:
                        articles.append(article_data)
                        seen_urls.add(href)
                        seen_titles.add(title_key)
                        section_tally[category_name] += 1
                        page_articles_found += 1
                        print(f"  Added article: {href}")
                        if len(articles) % 20 == 0:
                            save_articles(articles)
                    time.sleep(0.5)
        
        print(f"  Found {page_articles_found} new articles on this page")
        
        # Handle 'Load More Articles' button
        load_more_btn = find_load_more_button(soup)
        if load_more_btn and load_more_btn.parent and load_more_btn.parent.name == 'a':
            next_url = urljoin(url, load_more_btn.parent['href'])
        else:
            # Try to find a next page link or break
            next_url = None
            for a in soup.find_all('a', href=True):
                if a.text and a.text.strip().lower() == 'next':
                    next_url = urljoin(url, a['href'])
                    break
        
        if next_url and next_url not in visited_pages:
            url = next_url
        else:
            url = None
        
        page_count += 1
        time.sleep(1)
    
    category_total = len(articles) - category_start_count
    print(f"--- Completed {category_name.upper()}: {category_total} new articles ---\n")
    
    save_articles(articles)
    return articles

def scrape_article_details(title, article_url, category):
    global session
    print(f"  Fetching article: {title}")
    
    try:
        art_resp = session.get(article_url, timeout=15)
        if art_resp.status_code != 200:
            print(f"    Failed to fetch article: {article_url}")
            return None
        
        art_soup = BeautifulSoup(art_resp.text, 'html.parser')
        if is_premium_content(art_soup):
            print(f"    Skipping premium content: {article_url}")
            return None
        
        # Try to extract date from <small class="text-wrap text-center">
        date = None
        date_tag = art_soup.find('small', class_='text-wrap text-center')
        if date_tag:
            date_str = date_tag.get_text(strip=True)
            # Example: '27 July 2025 - 20:13' or '21 July 2025 - 12:00'
            date_str = date_str.replace(' - ', ' ')
            date = parse_article_date(date_str)
            if date:
                date = date.strftime('%Y-%m-%d %H:%M')
            else:
                date = date_str  # fallback to raw string if parsing fails
        else:
            # Fallback to previous logic (e.g., <span class='article-date'>)
            date_tag = art_soup.find('span', class_='article-date')
            if date_tag:
                date_str = date_tag.get_text(strip=True)
                date = parse_article_date(date_str)
                if date:
                    date = date.strftime('%Y-%m-%d %H:%M')
                else:
                    date = date_str
        
        # Extract summary
        summary = ''
        summary_div = art_soup.find('div', class_='article-summary')
        if summary_div:
            summary = '\n'.join(li.get_text(strip=True) for li in summary_div.find_all('li'))
        
        # Extract content
        content = ''
        story_div = art_soup.find('div', class_='story-content')
        if story_div:
            paragraphs = story_div.find_all('p')
            content = '\n'.join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        
        # Extract subheadings (if any)
        subheadings = [h2.get_text(strip=True) for h2 in story_div.find_all('h2')] if story_div else []
        
        # If no content, fallback to all <p> on page
        if not content:
            paragraphs = art_soup.find_all('p')
            content = '\n'.join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        
        return {
            'title': title,
            'url': article_url,
            'date': date,
            'summary': summary,
            'content': content,
            'subheadings': subheadings,
            'category': category
        }
    except Exception as e:
        print(f"    Error fetching article: {e}")
        return None

def scrape_multiple_categories(category_urls, max_pages=50):
    # Initialize session at the start
    initialize_session()
    
    try:
        all_articles = load_existing_articles()
        seen_urls = set(a['url'] for a in all_articles)
        seen_titles = set(a['title'].strip().lower() for a in all_articles if a.get('title'))
        
        print(f"Starting scrape with {len(all_articles)} existing articles")
        print_section_tallies()
        
        # Scrape homepage first
        print("\n" + "="*60)
        print("SCRAPING HOMEPAGE")
        print("="*60)
        scrape_homepage(all_articles, seen_urls, seen_titles)
        
        # Then scrape each category
        print("\n" + "="*60)
        print("SCRAPING CATEGORIES")
        print("="*60)
        for i, url in enumerate(category_urls, 1):
            category_name = url.split("/")[-1] if url.split("/")[-1] else url.split("/")[-2]
            print(f"\n[{i}/{len(category_urls)}] Processing category: {category_name}")
            category_articles = scrape_category(url, max_pages=max_pages)
            # Update all_articles with new ones (avoid duplicates)
            existing_urls = set(a['url'] for a in all_articles)
            for article in category_articles:
                if article['url'] not in existing_urls:
                    all_articles.append(article)
                    existing_urls.add(article['url'])
        
        # Remove duplicates and save final result
        seen = set()
        unique_articles = []
        for art in all_articles:
            if art['url'] not in seen:
                unique_articles.append(art)
                seen.add(art['url'])
        
        save_articles(unique_articles)
        
        print("\n" + "="*60)
        print("SCRAPING COMPLETE!")
        print("="*60)
        print(f"Total unique articles saved: {len(unique_articles)}")
        print_section_tallies()
        
    finally:
        # Always close the session when done
        close_session()

if __name__ == "__main__":
    # List of category URLs (counties)
    category_urls = [
        # Counties main and sub
        "https://www.the-star.co.ke/counties",
        "https://www.the-star.co.ke/counties/rift-valley",
        "https://www.the-star.co.ke/counties/nairobi",
        "https://www.the-star.co.ke/counties/north-eastern",
        "https://www.the-star.co.ke/counties/coast",
        "https://www.the-star.co.ke/counties/central",
        "https://www.the-star.co.ke/counties/nyanza",
        "https://www.the-star.co.ke/counties/western",
        "https://www.the-star.co.ke/counties/eastern",
        # Business main and sub
        "https://www.the-star.co.ke/business",
        "https://www.the-star.co.ke/business/kenya",
        "https://www.the-star.co.ke/business/markets",
        "https://www.the-star.co.ke/business/commentary",
        # Health
        "https://www.the-star.co.ke/health",
        # Sports main and sub
        "https://www.the-star.co.ke/sports",
        "https://www.the-star.co.ke/sports/football",
        "https://www.the-star.co.ke/sports/athletics",
        "https://www.the-star.co.ke/sports/rugby",
        "https://www.the-star.co.ke/sports/tennis",
        "https://www.the-star.co.ke/sports/golf",
        "https://www.the-star.co.ke/sports/boxing",
        "https://www.the-star.co.ke/sports/basketball",
        # Climate change
        "https://www.the-star.co.ke/climate-change",
        # Sasa main and sub
        "https://www.the-star.co.ke/sasa",
        "https://www.the-star.co.ke/sasa/lifestyle",
        "https://www.the-star.co.ke/sasa/technology",
        "https://www.the-star.co.ke/sasa/entertainment",
        "https://www.the-star.co.ke/sasa/society",
        "https://www.the-star.co.ke/sasa/fashion",
        "https://www.the-star.co.ke/sasa/food",
        "https://www.the-star.co.ke/sasa/travel",
        "https://www.the-star.co.ke/sasa/books",
        "https://www.the-star.co.ke/sasa/events"
    ]
    scrape_multiple_categories(category_urls, max_pages=50)