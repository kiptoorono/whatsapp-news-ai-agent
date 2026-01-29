import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urljoin
from requests.exceptions import RequestException, Timeout
import os
from datetime import datetime
import re
import random

# Helper to parse date strings like 'Tuesday 14th July, 2024 12:00 AM'
def parse_article_date(date_str):
    if not date_str:
        return None
    date_str = date_str.strip()
    # Remove ordinal suffixes (st, nd, rd, th)
    date_str = re.sub(r'(\d{1,2})(st|nd|rd|th)', r'\1', date_str)
    # Try with time and without
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

def save_articles(articles, filename='peopledaily_articles.json'):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"Progress saved: {len(articles)} articles.")

def load_existing_articles(filename='peopledaily_articles.json'):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except Exception:
                return []
    return []

def get_latest_date_for_category(articles, category):
    dates = [parse_article_date(a['date']) for a in articles if a.get('category') == category and a.get('date')]
    dates = [d for d in dates if d]
    return max(dates) if dates else None

def scrape_homepage(articles, seen_urls, seen_titles):
    url = "https://peopledaily.digital/"
    print(f"Scraping homepage: {url}")
    
    # Create a session for better request handling
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://www.google.com/"
    }
    session.headers.update(headers)
    
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
    # Try to find all news links (may need to adjust selector for homepage)
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text(strip=True)
        title_key = text.strip().lower() if text else ''
        # Only consider links that look like articles (skip nav, social, etc.)
        if href.startswith("https://peopledaily.digital/") and len(href) > len("https://peopledaily.digital/") and text:
            if href not in seen_urls and title_key and title_key not in seen_titles:
                # Try to guess category from URL
                parts = href.replace("https://peopledaily.digital/", "").split("/")
                category = parts[0] if len(parts) > 1 else "homepage"
                article_data = scrape_article_details(text, href, category, headers)
                if article_data:
                    articles.append(article_data)
                    seen_urls.add(href)
                    seen_titles.add(title_key)
                    print(f"  [Homepage] Added article: {href}")
                    if len(articles) % 20 == 0:
                        save_articles(articles)
                time.sleep(random.uniform(1, 3))  # Random delay between 1-3 seconds

def scrape_category(category_slug, category_name=None, max_pages=50, stop_on_existing=True):
    if category_name is None:
        category_name = category_slug
    articles = load_existing_articles()
    seen_urls = set(a['url'] for a in articles)
    seen_titles = set(a['title'].strip().lower() for a in articles if a.get('title'))
    visited_pages = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    start_urls = [
        f"https://peopledaily.digital/{category_slug}",
        f"https://peopledaily.digital/category/{category_slug}"
    ]
    for start_url in start_urls:
        url = start_url
        is_first_page = True
        page_count = 0
        while url and url not in visited_pages and page_count < max_pages:
            print(f"Scraping page: {url}")
            visited_pages.add(url)
            try:
                resp = requests.get(url, headers=headers, timeout=15)
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
            headlines = soup.find_all('a', href=True)
            page_article_urls = []
            for a in headlines:
                href = a['href']
                text = a.get_text(strip=True)
                title_key = text.strip().lower() if text else ''
                if f'/{category_slug}/' in href and text:
                    if href not in seen_urls and title_key and title_key not in seen_titles:
                        article_data = scrape_article_details(text, href, category_name, headers)
                        if article_data:
                            articles.append(article_data)
                            seen_urls.add(href)
                            seen_titles.add(title_key)
                            print(f"  Added article: {href}")
                            if len(articles) % 20 == 0:
                                save_articles(articles)
                        page_article_urls.append(href)
                        time.sleep(random.uniform(1, 3))  # Random delay between 1-3 seconds
                    else:
                        page_article_urls.append(href)
            if not page_article_urls:
                print(f"No new articles found in {category_name} on this page.")
            # On the first page, look for "Click for more" button
            next_link = None
            if is_first_page:
                for a in soup.find_all('a', href=True):
                    if a.text and 'click for more' in a.text.strip().lower():
                        next_link = a
                        break
                is_first_page = False
            # Otherwise, look for "Next" button
            if not next_link:
                for a in soup.find_all('a', href=True):
                    if a.text and a.text.strip().lower() == 'next':
                        next_link = a
                        break
            if next_link:
                next_url = urljoin(url, next_link['href'])
                if next_url not in visited_pages:
                    url = next_url
                else:
                    url = None
            else:
                url = None
            page_count += 1
            time.sleep(random.uniform(2, 5))  # Random delay between 2-5 seconds
    save_articles(articles)
    return articles

def scrape_article_details(title, article_url, category, headers):
    print(f"  Fetching article: {title}")
    try:
        art_resp = requests.get(article_url, headers=headers, timeout=15)
        if art_resp.status_code != 200:
            print(f"    Failed to fetch article: {article_url}")
            return None
        art_soup = BeautifulSoup(art_resp.text, 'html.parser')
        date_tag = art_soup.find('span', class_='content--date--date-time')
        date = date_tag.get_text(strip=True) if date_tag else None
        paragraphs = art_soup.find_all('p')
        content = '\n'.join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        subheadings = [h2.get_text(strip=True) for h2 in art_soup.find_all('h2', class_='wp-block-heading')]
        return {
            'title': title,
            'url': article_url,
            'date': date,
            'content': content,
            'subheadings': subheadings,
            'category': category
        }
    except Exception as e:
        print(f"    Error fetching article: {e}")
        return None

def scrape_multiple_categories(categories, max_pages=50, stop_on_existing=True):
    all_articles = load_existing_articles()
    seen_urls = set(a['url'] for a in all_articles)
    seen_titles = set(a['title'].strip().lower() for a in all_articles if a.get('title'))
    # Scrape homepage first
    scrape_homepage(all_articles, seen_urls, seen_titles)
    # Then scrape each category
    for cat in categories:
        all_articles += scrape_category(cat, max_pages=max_pages, stop_on_existing=stop_on_existing)
    seen = set()
    unique_articles = []
    for art in all_articles:
        if art['url'] not in seen:
            unique_articles.append(art)
            seen.add(art['url'])
    save_articles(unique_articles)
    print(f"Scraping complete. {len(unique_articles)} unique articles saved to peopledaily_articles.json.")

if __name__ == "__main__":
    categories = ['news', 'inside-politics', 'sports', 'business', 'insights', 'lifestyle']
    scrape_multiple_categories(categories, max_pages=50) 
