import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urljoin
from requests.exceptions import RequestException, Timeout
import os
from datetime import datetime
import re

# Helper to parse date strings like 'Tuesday 14th July, 2024 12:00 AM'
def parse_article_date(date_str):
    if not date_str:
        return None
    # Remove ordinal suffixes (st, nd, rd, th)
    date_str = re.sub(r'(\d{1,2})(st|nd|rd|th)', r'\1', date_str)
    # Try with time
    for fmt in ["%A %d %B, %Y %I:%M %p", "%A %d %B, %Y %I %p", "%A %d %B, %Y"]:
        try:
            return datetime.strptime(date_str, fmt)
        except Exception:
            continue
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

def scrape_category(category_slug, category_name=None, max_pages=100, min_date=None, stop_on_existing=True):
    if category_name is None:
        category_name = category_slug
    articles = load_existing_articles()
    seen_urls = set(a['url'] for a in articles)
    visited_pages = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    # Find latest date for this category if min_date not given
    if min_date is None:
        latest = get_latest_date_for_category(articles, category_name)
        min_date = latest
    if isinstance(min_date, str):
        min_date = parse_article_date(min_date)
    start_urls = [
        f"https://peopledaily.digital/{category_slug}",
        f"https://peopledaily.digital/category/{category_slug}"
    ]
    for start_url in start_urls:
        url = start_url
        is_first_page = True
        page_count = 0
        stop_scraping = False
        while url and url not in visited_pages and page_count < max_pages and not stop_scraping:
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
            all_existing = True
            for a in headlines:
                href = a['href']
                text = a.get_text(strip=True)
                if f'/{category_slug}/' in href and text:
                    if href not in seen_urls:
                        all_existing = False
                        article_data = scrape_article_details(text, href, category_name, headers)
                        if article_data:
                            article_date = parse_article_date(article_data.get('date'))
                            if min_date and article_date and article_date <= min_date:
                                print(f"  Article {href} is older than or equal to min_date. Stopping scrape for this category.")
                                stop_scraping = True
                                break
                            articles.append(article_data)
                            print(f"  Added article: {href}")
                            if len(articles) % 20 == 0:
                                save_articles(articles)
                        seen_urls.add(href)
                        page_article_urls.append(href)
                        time.sleep(0.5)
                    else:
                        page_article_urls.append(href)
            if not page_article_urls:
                print(f"No new articles found in {category_name} on this page.")
            # If all articles on this page are already in seen_urls, stop if stop_on_existing is True
            if stop_on_existing and all_existing and page_article_urls:
                print(f"All articles on this page already exist. Stopping scrape for {category_name}.")
                break
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
            time.sleep(1)
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

def scrape_multiple_categories(categories, max_pages=100, min_date=None, stop_on_existing=True):
    all_articles = load_existing_articles()
    for cat in categories:
        all_articles += scrape_category(cat, max_pages=max_pages, min_date=min_date, stop_on_existing=stop_on_existing)
    seen = set()
    unique_articles = []
    for art in all_articles:
        if art['url'] not in seen:
            unique_articles.append(art)
            seen.add(art['url'])
    save_articles(unique_articles)
    print(f"Scraping complete. {len(unique_articles)} unique articles saved to peopledaily_articles.json.")

if __name__ == "__main__":
    categories = ['business', 'lifestyle', 'insights']
    scrape_multiple_categories(categories, max_pages=100, stop_on_existing=True) 
