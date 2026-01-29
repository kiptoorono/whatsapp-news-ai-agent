import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urljoin
import re
from datetime import datetime

class StandardMediaScraper:
    def __init__(self, base_url="https://www.standardmedia.co.ke/", max_articles_per_section=50):
        self.base_url = base_url
        self.max_articles_per_section = max_articles_per_section
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }
        self.articles = []
        self.seen_urls = set()
        self.section_tallies = {}
        
        # Define sections to scrape
        self.sections = {
            "latest": "https://www.standardmedia.co.ke/latest",
            "national": "https://www.standardmedia.co.ke/category/588/national",
            "counties": "https://www.standardmedia.co.ke/category/1/counties", 
            "politics": "https://www.standardmedia.co.ke/category/3/politics",
            "world": "https://www.standardmedia.co.ke/category/5/world",
            "health": "https://www.standardmedia.co.ke/health",
            "sports": "https://www.standardmedia.co.ke/sports",
            "environment": "https://www.standardmedia.co.ke/category/63/environment"
        }

    def get_article_links_from_section(self, section_url, section_name):
        """Get article links from a specific section with load more support."""
        all_links = []
        visited_pages = set()
        page_count = 0
        
        print(f"  Scraping section: {section_name}")
        
        while page_count < 10:  # Limit pages to avoid infinite loops
            try:
                if page_count == 0:
                    url = section_url
                else:
                    # Handle load more functionality
                    if "category" in section_url:
                        # Extract category ID from URL
                        category_id = re.search(r'/category/(\d+)/', section_url)
                        if category_id:
                            start_index = page_count * 24  # Standard Media loads 24 articles per page
                            url = f"{section_url}?start={start_index}"
                        else:
                            break
                    else:
                        # For non-category pages, try pagination
                        url = f"{section_url}?page={page_count + 1}"
                
                if url in visited_pages:
                    break
                    
                visited_pages.add(url)
                print(f"    Fetching page: {url}")
                
                resp = requests.get(url, headers=self.headers, timeout=15)
                if resp.status_code != 200:
                    print(f"    Failed to fetch page: {url}, status code: {resp.status_code}")
                    break
                    
                soup = BeautifulSoup(resp.text, "html.parser")
                
                # Extract article links based on section
                section_links = []
                
                # Main headlines (h3 with mb-3 class)
                h3_links = [a['href'] for h3 in soup.find_all('h3', class_='mb-3') 
                           for a in h3.find_all('a', href=True)]
                section_links.extend(h3_links)
                
                # Sub-title links
                sub_title_links = [a['href'] for div in soup.find_all('div', class_='sub-title') 
                                  for a in div.find_all('a', href=True)]
                section_links.extend(sub_title_links)
                
                # Regular article links
                article_links = [a['href'] for a in soup.find_all('a', href=True) 
                               if '/article/' in a.get('href', '')]
                section_links.extend(article_links)
                
                # Sports section specific (h1 headlines)
                if section_name == "sports":
                    h1_links = [a['href'] for h1 in soup.find_all('h1', class_='mb-3') 
                               for a in h1.find_all('a', href=True)]
                    section_links.extend(h1_links)
                
                # Health section specific
                if section_name == "health":
                    health_links = [a['href'] for a in soup.find_all('a', href=True) 
                                   if '/health/' in a.get('href', '')]
                    section_links.extend(health_links)
                
                # Environment section specific
                if section_name == "environment":
                    env_links = [a['href'] for a in soup.find_all('a', href=True) 
                                if '/environment' in a.get('href', '')]
                    section_links.extend(env_links)
                
                # Deduplicate and add to all_links
                for link in section_links:
                    if link.startswith('/'):
                        link = urljoin(self.base_url, link)
                    if link not in all_links and link.startswith(self.base_url):
                        all_links.append(link)
                
                # Check if there's a load more button
                load_more_btn = soup.find('button', id='loadMoreButton')
                if not load_more_btn:
                    # No more pages to load
                    break
                
                page_count += 1
                time.sleep(1)  # Be respectful
                
            except Exception as e:
                print(f"    Error fetching page {url}: {e}")
                break
        
        print(f"    Found {len(all_links)} unique article links in {section_name}")
        return all_links

    def is_paywalled(self, soup):
        """Check if article is paywalled."""
        return soup.find('div', class_='subscribe-content') is not None

    def parse_article(self, url, section_name):
        """Parse individual article with enhanced extraction."""
        try:
            resp = requests.get(url, headers=self.headers, timeout=15)
            if resp.status_code != 200:
                print(f"    Failed to fetch article: {url}")
                return None
                
            soup = BeautifulSoup(resp.text, "html.parser")
            
            if self.is_paywalled(soup):
                print(f"    Skipping paywalled article: {url}")
                return None
            
            # Extract title
            title = ""
            h1 = soup.find('h1')
            if h1:
                title = h1.get_text(strip=True)
            if not title:
                h3 = soup.find('h3', class_='mb-3')
                if h3:
                    title = h3.get_text(strip=True)
            
            # Extract author and date
            author = None
            date = None
            
            # Try the new byline structure
            byline = soup.find('small', class_='text-muted byline-margin')
            if byline:
                byline_text = byline.get_text(" ", strip=True)
                # Look for author link
                author_link = byline.find('a')
                if author_link:
                    author = author_link.get_text(strip=True).replace("By", "").strip()
                
                # Extract date from byline text
                date_match = re.search(r'(\w+\.\s+\d{1,2},\s+\d{4})', byline_text)
                if date_match:
                    date = date_match.group(1)
            
            # Fallback date extraction
            if not date:
                # Look for date in various formats
                date_patterns = [
                    r'(\w+\.\s+\d{1,2},\s+\d{4})',
                    r'(\d{1,2}/\d{1,2}/\d{4})',
                    r'(\d{4}-\d{2}-\d{2})'
                ]
                for pattern in date_patterns:
                    date_match = re.search(pattern, soup.get_text())
                    if date_match:
                        date = date_match.group(1)
                        break
            
            # Extract category
            category = section_name.title()  # Use section name as default
            
            # Try to get more specific category
            cat_div = soup.find('div', class_='category')
            if cat_div:
                category = cat_div.get_text(strip=True)
            
            # Try breadcrumb navigation
            breadcrumbs = soup.find_all('li', class_='breadcrumb-item')
            if breadcrumbs:
                for breadcrumb in breadcrumbs:
                    a_tag = breadcrumb.find('a')
                    if a_tag and a_tag.get_text(strip=True).lower() not in ['home', 'news']:
                        category = a_tag.get_text(strip=True)
                        break
            
            # Extract content
            content = ""
            content_div = soup.find('div', class_='bf8pwj6RNn content')
            if not content_div:
                content_div = soup.find('div', class_='mb-4')
            
            if content_div:
                # Try different paragraph classes
                paragraphs = content_div.find_all('p', class_='card-text')
                if not paragraphs:
                    paragraphs = content_div.find_all('p')
                
                content = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            
            # Fallback content extraction
            if not content:
                paragraphs = soup.find_all('p')
                content = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            
            if not content or len(content) < 50:  # Minimum content length
                print(f"    No sufficient content found for: {url}")
                return None
            
            return {
                "title": title,
                "url": url,
                "date": date,
                "author": author,
                "category": category,
                "section": section_name,
                "content": content
            }
            
        except Exception as e:
            print(f"    Error parsing article {url}: {e}")
            return None

    def scrape_section(self, section_name, section_url):
        """Scrape a specific section."""
        print(f"\n--- Starting scrape for section: {section_name.upper()} ---")
        
        links = self.get_article_links_from_section(section_url, section_name)
        section_articles = []
        
        for i, url in enumerate(links[:self.max_articles_per_section]):
            if url in self.seen_urls:
                continue
                
            print(f"  [{i+1}/{len(links)}] Scraping: {url}")
            article = self.parse_article(url, section_name)
            
            if article:
                self.articles.append(article)
                section_articles.append(article)
                self.seen_urls.add(url)
                
                # Update section tally
                self.section_tallies[section_name] = self.section_tallies.get(section_name, 0) + 1
                
                # Save progress every 10 articles
                if len(self.articles) % 10 == 0:
                    self.save_progress()
                    
            time.sleep(0.5)  # Be respectful
        
        print(f"--- Completed {section_name.upper()}: {len(section_articles)} new articles ---")
        return section_articles

    def scrape_all_sections(self):
        """Scrape all defined sections."""
        print(" Starting Standard Media comprehensive scrape...")
        
        for section_name, section_url in self.sections.items():
            try:
                self.scrape_section(section_name, section_url)
                self.print_section_tallies()
            except Exception as e:
                print(f"❌ Error scraping section {section_name}: {e}")
                continue
        
        print(f"\n Scraping complete! Total articles: {len(self.articles)}")
        self.print_final_tallies()

    def print_section_tallies(self):
        """Print current section tallies."""
        print("\n" + "="*50)
        print("SECTION TALLIES")
        print("="*50)
        for section, count in sorted(self.section_tallies.items()):
            print(f"{section:<20} : {count:>4} articles")
        print("-"*50)
        print(f"TOTAL{'':<15} : {len(self.articles):>4} articles")
        print("="*50 + "\n")

    def print_final_tallies(self):
        """Print final section tallies."""
        print("\n" + "="*50)
        print("FINAL SECTION TALLIES")
        print("="*50)
        for section, count in sorted(self.section_tallies.items()):
            print(f"{section:<20} : {count:>4} articles")
        print("-"*50)
        print(f"TOTAL{'':<15} : {len(self.articles):>4} articles")
        print("="*50)

    def save_progress(self, filename="standard_articles.json"):
        """Save current progress to file."""
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.articles, f, ensure_ascii=False, indent=2)
        print(f"Progress saved: {len(self.articles)} articles.")

    def save(self, filename="standard_articles.json"):
        """Save final results to file."""
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.articles, f, ensure_ascii=False, indent=2)
        print(f" Saved {len(self.articles)} articles to {filename}")

if __name__ == "__main__":
    scraper = StandardMediaScraper(max_articles_per_section=30)
    scraper.scrape_all_sections()
    scraper.save(filename="standard_articles_comprehensive.json")
