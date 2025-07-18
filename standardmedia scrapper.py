import requests
from bs4 import BeautifulSoup
import json
import time

class StandardMediaScraper:
    def __init__(self, base_url="https://www.standardmedia.co.ke/", max_articles=50):
        self.base_url = base_url
        self.max_articles = max_articles
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }
        self.articles = []
        self.seen_urls = set()

    def get_article_links(self):
        resp = requests.get(self.base_url, headers=self.headers)
        soup = BeautifulSoup(resp.text, "html.parser")
        # Main news: <a ...><h1>...</h1></a>
        main_links = [a['href'] for a in soup.find_all('a', href=True) if a.find('h1')]
        # Sub-news: <div class="sub-title mb-2"><a href="...">...</a></div>
        sub_links = [a['href'] for div in soup.find_all('div', class_='sub-title mb-2') for a in div.find_all('a', href=True)]
        # Latest news: <h3 class="mb-3"><a ...></a></h3>
        latest_links = [a['href'] for h3 in soup.find_all('h3', class_='mb-3') for a in h3.find_all('a', href=True)]
        # Also fetch from the 'Latest' section page
        latest_section_links = []
        try:
            latest_resp = requests.get("https://www.standardmedia.co.ke/latest", headers=self.headers)
            latest_soup = BeautifulSoup(latest_resp.text, "html.parser")
            latest_section_links = [a['href'] for h3 in latest_soup.find_all('h3', class_='mb-3') for a in h3.find_all('a', href=True)]
        except Exception as e:
            print(f"  Error fetching latest section: {e}")
        # Combine and deduplicate
        all_links = list(dict.fromkeys(main_links + sub_links + latest_links + latest_section_links))
        return all_links[:self.max_articles]

    def is_paywalled(self, soup):
        return soup.find('div', class_='subscribe-content') is not None

    def parse_article(self, url):
        try:
            resp = requests.get(url, headers=self.headers)
            soup = BeautifulSoup(resp.text, "html.parser")
            if self.is_paywalled(soup):
                print(f"  Skipping paywalled article: {url}")
                return None
            h1 = soup.find('h1')
            title = h1.get_text(strip=True) if h1 else ""
            # Author and date (new structure)
            author = None
            date = None
            # Try to find the author and date in the latest news structure
            d_flex = soup.find('div', class_='d-flex align-items-baseline justify-content-between')
            if d_flex:
                author_a = d_flex.find('a', attrs={'aria-label': True})
                if author_a and author_a.find('small', class_='text-muted'):
                    author = author_a.find('small', class_='text-muted').get_text(strip=True).replace("By", "").strip()
                smalls = d_flex.find_all('small', class_='text-muted')
                if len(smalls) > 1:
                    date = smalls[1].get_text(strip=True)
            # Fallback to previous byline logic
            if not author or not date:
                byline = soup.find('small', class_='text-muted byline-margin')
                if byline:
                    byline_text = byline.get_text(" ", strip=True)
                    if "|" in byline_text:
                        parts = byline_text.split("|")
                        if not author:
                            author = parts[0].replace("By", "").strip()
                        if not date:
                            date = parts[1].strip()
                    else:
                        if not author:
                            author = byline_text
            # Category
            category = None
            cat_div = soup.find('div', class_='category')
            if cat_div:
                category = cat_div.get_text(strip=True)
            if not category:
                # Try <h2><a ... aria-label="National">National</a></h2>
                h2 = soup.find('h2')
                if h2 and h2.find('a', attrs={'aria-label': True}):
                    category = h2.find('a', attrs={'aria-label': True}).get_text(strip=True)
            if not category:
                # Try breadcrumb
                breadcrumb = soup.find_all('li', class_='breadcrumb-item')
                if breadcrumb:
                    last_breadcrumb = breadcrumb[-1]
                    a_tag = last_breadcrumb.find('a')
                    if a_tag:
                        category = a_tag.get_text(strip=True)
            # Content extraction as before...
            content_div = soup.find('div', class_='bf8pwj6RNn content')
            if not content_div:
                content_div = soup.find('div', class_='mb-4')
            paragraphs = content_div.find_all('p', class_='card-text') if content_div else []
            content = "\n".join(p.get_text(strip=True) for p in paragraphs)
            if not content:
                paragraphs = content_div.find_all('p') if content_div else []
                content = "\n".join(p.get_text(strip=True) for p in paragraphs)
            if not content:
                paragraphs = soup.find_all('p')
                content = "\n".join(p.get_text(strip=True) for p in paragraphs)
            if not content:
                print(f"  No content found for: {url}")
                return None
            return {
                "title": title,
                "url": url,
                "date": date,
                "author": author,
                "category": category,
                "content": content
            }
        except Exception as e:
            print(f"  Error parsing article {url}: {e}")
            return None

    def scrape(self):
        links = self.get_article_links()
        print(f"Found {len(links)} article links.")
        for url in links:
            if url in self.seen_urls:
                continue
            print(f"Scraping: {url}")
            article = self.parse_article(url)
            if article:
                self.articles.append(article)
                self.seen_urls.add(url)
            time.sleep(1)
        return self.articles

    def save(self, filename="standard_articles.json"):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.articles, f, ensure_ascii=False, indent=2)
        print(f"Saved {len(self.articles)} articles to {filename}")

if __name__ == "__main__":
    scraper = StandardMediaScraper(max_articles=30)  # Adjust as needed
    articles = scraper.scrape()
    scraper.save(filename="standard_articles_trial.json")
