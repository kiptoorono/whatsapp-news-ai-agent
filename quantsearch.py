import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import re
import os
from dotenv import load_dotenv

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer
from openai import OpenAI

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NewsSearchAgent:
    """Enhanced news search agent with AI-powered summarization and filtering."""
    
    def __init__(
        self,
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        collection_name: str = "peopledaily_articles",
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        samba_api_key: Optional[str] = None
    ):
        self.qdrant_host = qdrant_host
        self.qdrant_port = qdrant_port
        self.collection_name = collection_name
        self.model_name = model_name
        self.samba_api_key = samba_api_key
        
        # Initialize components
        self.qdrant_client = None
        self.model = None
        self.samba_client = None
        
        self._connect_to_services()
    
    def _connect_to_services(self) -> None:
        """Initialize connections to all services."""
        try:
            # Connect to Qdrant
            logger.info(f"Connecting to Qdrant at {self.qdrant_host}:{self.qdrant_port}")
            self.qdrant_client = QdrantClient(host=self.qdrant_host, port=self.qdrant_port)
            
            # Load embedding model
            logger.info(f"Loading embedding model: {self.model_name}")
            self.model = SentenceTransformer(self.model_name)
            
            # Initialize SambaNova client if API key provided
            if self.samba_api_key:
                logger.info("Initializing SambaNova client")
                self.samba_client = OpenAI(
                    base_url="https://api.sambanova.ai/v1",
                    api_key=self.samba_api_key,
                )
            
            logger.info("All services connected successfully")
            
        except Exception as e:
            logger.error(f"Failed to connect to services: {e}")
            raise
    
    def summarize_with_sambanova(
        self, 
        text: str, 
        sentences: int = 2, 
        model: str = "Meta-Llama-3.1-405B-Instruct"
    ) -> str:
        """Summarize text using SambaNova API."""
        if not self.samba_client:
            return "[SambaNova client not initialized]"
        
        prompt = (
            f"Summarize the following news article in exactly {sentences} sentences. "
            "Be factual, neutral, and avoid speculation or opinion. "
            "Do not add information that is not present in the article.\n\n"
            f"{text}"
        )
        
        try:
            response = self.samba_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that provides accurate news summaries."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"SambaNova API error: {e}")
            return f"[SambaNova API error: {str(e)}]"
    
    def search_articles(
        self, 
        query: str, 
        top_k: int = 5,
        score_threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Search for articles using vector similarity."""
        try:
            # Generate query embedding
            query_vector = self.model.encode(query).tolist()
            
            # Search Qdrant
            hits = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True
            )
            
            # Format results
            results = []
            for hit in hits:
                result = {
                    "score": hit.score,
                    "title": hit.payload.get("title", ""),
                    "url": hit.payload.get("url", ""),
                    "date": hit.payload.get("date", ""),
                    "category": hit.payload.get("category", ""),
                    "content": hit.payload.get("content", ""),
                    "subheadings": hit.payload.get("subheadings", [])
                }
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def search_and_summarize(
        self, 
        query: str, 
        top_k: int = 3,
        summary_sentences: int = 2,
        score_threshold: float = 0.5
    ) -> str:
        """Search articles and return formatted results with summaries."""
        results = self.search_articles(query, top_k, score_threshold)
        
        if not results:
            return f"No articles found for query: '{query}'"
        
        formatted_results = []
        formatted_results.append(f" Search Results for: '{query}'\n{'='*50}")
        
        for i, result in enumerate(results, 1):
            content = result.get("content", "")
            
            # Generate summary if content exists and SambaNova is available
            if content and self.samba_client:
                summary = self.summarize_with_sambanova(content, summary_sentences)
            elif content:
                # Fallback: use first few sentences
                sentences = re.split(r'[.!?]+', content)
                summary = '. '.join(sentences[:summary_sentences]).strip()
                if summary and not summary.endswith('.'):
                    summary += '.'
            else:
                summary = "[No content available]"
            
            # Format result
            result_text = f"""
 Article {i} (Score: {result['score']:.3f})
Title: {result['title']}
Date: {result['date']}
Category: {result['category']}
Summary: {summary}
URL: {result['url']}
"""
            formatted_results.append(result_text)
        
        return "\n".join(formatted_results)
    
    def search_by_category(
        self, 
        query: str, 
        category: str, 
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Search articles within a specific category."""
        try:
            query_vector = self.model.encode(query).tolist()
            
            hits = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="category",
                            match=models.MatchValue(value=category)
                        )
                    ]
                ),
                limit=top_k,
                with_payload=True
            )
            
            results = []
            for hit in hits:
                result = {
                    "score": hit.score,
                    "title": hit.payload.get("title", ""),
                    "url": hit.payload.get("url", ""),
                    "date": hit.payload.get("date", ""),
                    "category": hit.payload.get("category", ""),
                    "content": hit.payload.get("content", "")
                }
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Category search failed: {e}")
            return []
    
    def search_by_date_range(
        self, 
        query: str, 
        start_date: str, 
        end_date: str, 
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Search articles within a date range."""
        try:
            query_vector = self.model.encode(query).tolist()
            
            hits = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="date",
                            range=models.Range(
                                gte=start_date,
                                lte=end_date
                            )
                        )
                    ]
                ),
                limit=top_k,
                with_payload=True
            )
            
            results = []
            for hit in hits:
                result = {
                    "score": hit.score,
                    "title": hit.payload.get("title", ""),
                    "url": hit.payload.get("url", ""),
                    "date": hit.payload.get("date", ""),
                    "category": hit.payload.get("category", ""),
                    "content": hit.payload.get("content", "")
                }
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Date range search failed: {e}")
            return []
    
    def get_article_statistics(self) -> Dict[str, Any]:
        """Get statistics about the article collection."""
        try:
            collection_info = self.qdrant_client.get_collection(self.collection_name)
            
            # Get sample articles to analyze categories
            sample_results = self.qdrant_client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                with_payload=True
            )
            
            categories = {}
            dates = []
            
            for result in sample_results[0]:
                category = result.payload.get("category", "unknown")
                categories[category] = categories.get(category, 0) + 1
                
                date = result.payload.get("date", "")
                if date:
                    dates.append(date)
            
            stats = {
                "total_articles": collection_info.points_count,
                "vector_size": collection_info.config.params.vectors.size,
                "categories": categories,
                "date_range": {
                    "earliest": min(dates) if dates else "Unknown",
                    "latest": max(dates) if dates else "Unknown"
                }
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
    
    def interactive_search(self) -> None:
        """Interactive search interface."""
        print("🤖 News Search Agent - Interactive Mode")
        print("Commands:")
        print("  search <query>                    - Search articles")
        print("  category <category> <query>       - Search in specific category")
        print("  date <start_date> <end_date> <query> - Search in date range")
        print("  stats                             - Show collection statistics")
        print("  help                              - Show this help")
        print("  quit                              - Exit")
        print("-" * 60)
        
        while True:
            try:
                user_input = input("\n Enter command: ").strip()
                
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print(" Goodbye!")
                    break
                
                elif user_input.lower() == 'help':
                    print("\nCommands:")
                    print("  search <query>                    - Search articles")
                    print("  category <category> <query>       - Search in specific category")
                    print("  date <start_date> <end_date> <query> - Search in date range")
                    print("  stats                             - Show collection statistics")
                    print("  help                              - Show this help")
                    print("  quit                              - Exit")
                
                elif user_input.lower() == 'stats':
                    stats = self.get_article_statistics()
                    print("\n Collection Statistics:")
                    print(f"Total Articles: {stats.get('total_articles', 'Unknown')}")
                    print(f"Vector Size: {stats.get('vector_size', 'Unknown')}")
                    print("Categories:", stats.get('categories', {}))
                    print("Date Range:", stats.get('date_range', {}))
                
                elif user_input.lower().startswith('search '):
                    query = user_input[7:].strip()
                    if query:
                        results = self.search_and_summarize(query)
                        print(results)
                    else:
                        print("❌ Please provide a search query")
                
                elif user_input.lower().startswith('category '):
                    parts = user_input[9:].strip().split(' ', 1)
                    if len(parts) == 2:
                        category, query = parts
                        results = self.search_by_category(query, category)
                        if results:
                            print(f"\n Results for '{query}' in category '{category}':")
                            for i, result in enumerate(results, 1):
                                print(f"\n{i}. {result['title']} (Score: {result['score']:.3f})")
                                print(f"   Date: {result['date']}")
                                print(f"   URL: {result['url']}")
                        else:
                            print(f"❌ No results found for '{query}' in category '{category}'")
                    else:
                        print("❌ Usage: category <category_name> <search_query>")
                
                elif user_input.lower().startswith('date '):
                    parts = user_input[5:].strip().split(' ', 2)
                    if len(parts) == 3:
                        start_date, end_date, query = parts
                        results = self.search_by_date_range(query, start_date, end_date)
                        if results:
                            print(f"\n Results for '{query}' between {start_date} and {end_date}:")
                            for i, result in enumerate(results, 1):
                                print(f"\n{i}. {result['title']} (Score: {result['score']:.3f})")
                                print(f"   Date: {result['date']}")
                                print(f"   URL: {result['url']}")
                        else:
                            print(f"❌ No results found for '{query}' in date range {start_date} to {end_date}")
                    else:
                        print("❌ Usage: date <start_date> <end_date> <search_query>")
                
                else:
                    print("❌ Unknown command. Type 'help' for available commands.")
            
            except KeyboardInterrupt:
                print("\n Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")

    def parse_time_expression(self, query: str) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Parse time expressions from query and return (cleaned_query, start_date, end_date).
        
        Examples:
        - "news from last week" -> ("news", "2025-07-20", "2025-07-27")
        - "articles from yesterday" -> ("articles", "2025-07-26", "2025-07-26")
        - "politics this month" -> ("politics", "2025-07-01", "2025-07-31")
        """
        now = datetime.now()
        cleaned_query = query.lower()
        
        # Time patterns to match
        time_patterns = {
            r'\b(yesterday|yesterday\'s)\b': (now - timedelta(days=1), now - timedelta(days=1)),
            r'\b(today|today\'s)\b': (now, now),
            r'\b(last week|past week)\b': (now - timedelta(days=7), now),
            r'\b(this week)\b': (now - timedelta(days=now.weekday()), now),
            r'\b(last month|past month)\b': (now - timedelta(days=30), now),
            r'\b(this month)\b': (now.replace(day=1), now),
            r'\b(last year|past year)\b': (now - timedelta(days=365), now),
            r'\b(this year)\b': (now.replace(month=1, day=1), now),
            r'\b(last 3 days|past 3 days)\b': (now - timedelta(days=3), now),
            r'\b(last 7 days|past 7 days)\b': (now - timedelta(days=7), now),
            r'\b(last 30 days|past 30 days)\b': (now - timedelta(days=30), now),
            r'\b(last 2 weeks|past 2 weeks)\b': (now - timedelta(days=14), now),
            r'\b(last 3 weeks|past 3 weeks)\b': (now - timedelta(days=21), now),
        }
        
        start_date = None
        end_date = None
        
        for pattern, (start, end) in time_patterns.items():
            if re.search(pattern, cleaned_query):
                start_date = start.strftime('%Y-%m-%d')
                end_date = end.strftime('%Y-%m-%d')
                # Remove the time expression from the query
                cleaned_query = re.sub(pattern, '', cleaned_query).strip()
                break
        
        # Handle specific date ranges like "from X to Y"
        date_range_pattern = r'\bfrom\s+(\d{1,2}(?:st|nd|rd|th)?\s+\w+)\s+to\s+(\d{1,2}(?:st|nd|rd|th)?\s+\w+)\b'
        match = re.search(date_range_pattern, cleaned_query)
        if match:
            try:
                start_str, end_str = match.groups()
                # Parse dates (simplified - you might want more robust parsing)
                start_date = self._parse_relative_date(start_str, now)
                end_date = self._parse_relative_date(end_str, now)
                cleaned_query = re.sub(date_range_pattern, '', cleaned_query).strip()
            except:
                pass
        
        return cleaned_query, start_date, end_date
    
    def _parse_relative_date(self, date_str: str, reference_date: datetime) -> str:
        """Parse relative date expressions like '15th July' or 'last Monday'."""
        # Remove ordinal suffixes
        date_str = re.sub(r'(\d{1,2})(st|nd|rd|th)', r'\1', date_str)
        
        # Try to parse as "day month" format
        try:
            parsed_date = datetime.strptime(date_str, "%d %B")
            # Use current year
            return parsed_date.replace(year=reference_date.year).strftime('%Y-%m-%d')
        except:
            pass
        
        # Handle "last Monday" type expressions
        weekday_pattern = r'last\s+(\w+)'
        match = re.search(weekday_pattern, date_str.lower())
        if match:
            weekday_name = match.group(1)
            weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            if weekday_name in weekdays:
                target_weekday = weekdays.index(weekday_name)
                current_weekday = reference_date.weekday()
                days_back = (current_weekday - target_weekday) % 7
                if days_back == 0:
                    days_back = 7
                target_date = reference_date - timedelta(days=days_back)
                return target_date.strftime('%Y-%m-%d')
        
        return reference_date.strftime('%Y-%m-%d')

    def search_and_summarize_time_aware(
        self, 
        query: str, 
        top_k: int = 3,
        summary_sentences: int = 2,
        score_threshold: float = 0.5
    ) -> str:
        """
        Enhanced search that automatically detects and applies time filters.
        """
        # Parse time expressions from the query
        cleaned_query, start_date, end_date = self.parse_time_expression(query)
        
        if start_date and end_date:
            logger.info(f"Time-aware search: '{cleaned_query}' from {start_date} to {end_date}")
            results = self.search_by_date_range(cleaned_query, start_date, end_date, top_k)
        else:
            logger.info(f"Regular search: '{cleaned_query}'")
            results = self.search_articles(cleaned_query, top_k, score_threshold)
        
        if not results:
            time_info = f" from {start_date} to {end_date}" if start_date and end_date else ""
            return f"No articles found for query: '{cleaned_query}'{time_info}"
        
        formatted_results = []
        time_info = f" from {start_date} to {end_date}" if start_date and end_date else ""
        formatted_results.append(f"📰 Search Results for: '{cleaned_query}'{time_info}\n{'='*60}")
        
        for i, result in enumerate(results, 1):
            content = result.get("content", "")
            
            # Generate summary if content exists and SambaNova is available
            if content and self.samba_client:
                summary = self.summarize_with_sambanova(content, summary_sentences)
            elif content:
                # Fallback: use first few sentences
                sentences = re.split(r'[.!?]+', content)
                summary = '. '.join(sentences[:summary_sentences]).strip()
                if summary and not summary.endswith('.'):
                    summary += '.'
            else:
                summary = "[No content available]"
            
            # Format result
            result_text = f"""
📄 Article {i} (Score: {result['score']:.3f})
📰 Title: {result['title']}
📅 Date: {result['date']}
🏷️ Category: {result['category']}
📝 Summary: {summary}
🔗 URL: {result['url']}
"""
            formatted_results.append(result_text)
        
        return "\n".join(formatted_results)

def main():
    """Main function to start the interactive search agent."""
    # Get API key from environment variable
    SAMBA_API_KEY = os.getenv("SAMBA_API_KEY")
    
    # Initialize search agent
    search_agent = NewsSearchAgent(
        qdrant_host="localhost",
        qdrant_port=6333,
        collection_name="peopledaily_articles",
        samba_api_key=SAMBA_API_KEY
    )
    
    # Start interactive mode
    search_agent.interactive_search()

if __name__ == "__main__":
    main()