import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import hashlib

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import ResponseHandlingException
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('news_pipeline.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class NewsEmbeddingPipeline:
    """Enhanced pipeline for embedding news articles and uploading to Qdrant vector database."""
    
    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        collection_name: str = "peopledaily_articles",
        batch_size: int = 256
    ):
        self.model_name = model_name
        self.qdrant_host = qdrant_host
        self.qdrant_port = qdrant_port
        self.collection_name = collection_name
        self.batch_size = batch_size
        
        # Initialize components
        self.model = None
        self.client = None
        
    def _load_model(self) -> None:
        """Load the sentence transformer model."""
        try:
            logger.info(f"Loading embedding model: {self.model_name}")
            self.model = SentenceTransformer(self.model_name)
            logger.info("Model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise
    
    def _connect_to_qdrant(self) -> None:
        """Establish connection to Qdrant."""
        try:
            logger.info(f"Connecting to Qdrant at {self.qdrant_host}:{self.qdrant_port}")
            self.client = QdrantClient(host=self.qdrant_host, port=self.qdrant_port)
            # Test connection
            self.client.get_collections()
            logger.info("Connected to Qdrant successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")
            raise
    
    def load_articles(self, file_path: str) -> List[Dict[str, Any]]:
        """Load articles from JSON file with validation."""
        try:
            path = Path(file_path)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            
            logger.info(f"Loading articles from: {file_path}")
            with open(path, "r", encoding="utf-8") as f:
                articles = json.load(f)
            
            # Validate articles structure
            validated_articles = []
            for i, article in enumerate(articles):
                if self._validate_article(article, i):
                    validated_articles.append(article)
            
            logger.info(f"Loaded {len(validated_articles)} valid articles out of {len(articles)}")
            return validated_articles
            
        except Exception as e:
            logger.error(f"Failed to load articles: {e}")
            raise
    
    def _validate_article(self, article: Dict[str, Any], index: int) -> bool:
        """Validate article structure."""
        required_fields = ['title', 'content']
        for field in required_fields:
            if field not in article or not article[field]:
                logger.warning(f"Article {index} missing required field: {field}")
                return False
        return True
    
    def _generate_article_hash(self, article: Dict[str, Any]) -> str:
        """Generate unique hash for article to avoid duplicates."""
        content = f"{article['title']}{article.get('url', '')}{article.get('date', '')}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def embed_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate embeddings for articles."""
        if not self.model:
            self._load_model()
        
        logger.info("Starting embedding generation...")
        embedded_articles = []
        
        for article in tqdm(articles, desc="Generating embeddings"):
            try:
                # Combine title and content for embedding
                text = f"{article['title']}\n{article['content']}"
                
                # Generate embedding
                embedding = self.model.encode(text, show_progress_bar=False).tolist()
                
                # Create embedded article
                embedded_article = {
                    "id": self._generate_article_hash(article),
                    "title": article["title"],
                    "url": article.get("url", ""),
                    "date": article.get("date", ""),
                    "category": article.get("category", ""),
                    "subheadings": article.get("subheadings", []),
                    "content": article["content"],
                    "embedding": embedding,
                    "processed_at": datetime.now().isoformat()
                }
                
                embedded_articles.append(embedded_article)
                
            except Exception as e:
                logger.error(f"Failed to embed article '{article.get('title', 'Unknown')}': {e}")
                continue
        
        logger.info(f"Generated embeddings for {len(embedded_articles)} articles")
        return embedded_articles
    
    def save_embeddings(self, embedded_articles: List[Dict[str, Any]], output_path: str) -> None:
        """Save embedded articles to JSON file."""
        try:
            logger.info(f"Saving embeddings to: {output_path}")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(embedded_articles, f, ensure_ascii=False, indent=2)
            logger.info("Embeddings saved successfully")
        except Exception as e:
            logger.error(f"Failed to save embeddings: {e}")
            raise
    
    def setup_collection(self, vector_size: int) -> None:
        """Create or recreate Qdrant collection."""
        if not self.client:
            self._connect_to_qdrant()
        
        try:
            # Check if collection exists
            existing_collections = [c.name for c in self.client.get_collections().collections]
            
            if self.collection_name in existing_collections:
                logger.info(f"Collection '{self.collection_name}' already exists")
                # Optionally recreate for fresh start
                response = input(f"Recreate collection '{self.collection_name}'? (y/N): ")
                if response.lower() == 'y':
                    self.client.delete_collection(self.collection_name)
                    logger.info(f"Deleted existing collection: {self.collection_name}")
                else:
                    return
            
            # Create collection
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size, 
                    distance=models.Distance.COSINE
                ),
            )
            logger.info(f"Created collection: {self.collection_name}")
            
        except Exception as e:
            logger.error(f"Failed to setup collection: {e}")
            raise
    
    def upload_to_qdrant(self, embedded_articles: List[Dict[str, Any]]) -> None:
        """Upload embedded articles to Qdrant in batches."""
        if not self.client:
            self._connect_to_qdrant()
        
        if not embedded_articles:
            logger.warning("No articles to upload")
            return
        
        # Setup collection
        vector_size = len(embedded_articles[0]["embedding"])
        self.setup_collection(vector_size)
        
        logger.info("Starting upload to Qdrant...")
        
        # Prepare points
        points = []
        for idx, article in enumerate(embedded_articles):
            try:
                point = models.PointStruct(
                    id=article["id"],  # Use hash as ID for deduplication
                    vector=article["embedding"],
                    payload={
                        "title": article["title"],
                        "url": article["url"],
                        "date": article["date"],
                        "category": article["category"],
                        "subheadings": article["subheadings"],
                        "content": article["content"],
                        "processed_at": article["processed_at"]
                    }
                )
                points.append(point)
            except Exception as e:
                logger.error(f"Failed to prepare point for article {idx}: {e}")
                continue
        
        # Upload in batches
        successful_uploads = 0
        for i in tqdm(range(0, len(points), self.batch_size), desc="Uploading batches"):
            batch = points[i:i+self.batch_size]
            try:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=batch
                )
                successful_uploads += len(batch)
            except ResponseHandlingException as e:
                logger.error(f"Failed to upload batch {i//self.batch_size + 1}: {e}")
                continue
        
        logger.info(f"Upload complete! {successful_uploads} articles uploaded successfully")
    
    def search_similar(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for similar articles using query embedding."""
        if not self.model:
            self._load_model()
        if not self.client:
            self._connect_to_qdrant()
        
        try:
            # Embed query
            query_embedding = self.model.encode(query).tolist()
            
            # Search
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=limit,
                with_payload=True
            )
            
            return [
                {
                    "score": result.score,
                    "title": result.payload.get("title"),
                    "url": result.payload.get("url"),
                    "content": result.payload.get("content")[:200] + "..."
                }
                for result in results
            ]
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def run_pipeline(self, input_path: str, output_path: Optional[str] = None, upload: bool = True) -> None:
        """Run the complete pipeline."""
        try:
            # Load articles
            articles = self.load_articles(input_path)
            
            # Generate embeddings
            embedded_articles = self.embed_articles(articles)
            
            # Save embeddings if output path provided
            if output_path:
                self.save_embeddings(embedded_articles, output_path)
            
            # Upload to Qdrant
            if upload:
                self.upload_to_qdrant(embedded_articles)
            
            logger.info("Pipeline completed successfully!")
            
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            raise

def main():
    """Main execution function."""
    # Configuration
    config = {
        "input_path": r"C:\Users\Rono\Desktop\Ai agent trial\peopledaily_articles.json",
        "output_path": r"C:\Users\Rono\Desktop\Ai agent trial\peopledaily_articles_embedded.json",
        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
        "qdrant_host": "localhost",
        "qdrant_port": 6333,
        "collection_name": "peopledaily_articles",
        "batch_size": 256
    }
    
    # Initialize pipeline
    pipeline = NewsEmbeddingPipeline(
        model_name=config["model_name"],
        qdrant_host=config["qdrant_host"],
        qdrant_port=config["qdrant_port"],
        collection_name=config["collection_name"],
        batch_size=config["batch_size"]
    )
    
    # Run pipeline
    pipeline.run_pipeline(
        input_path=config["input_path"],
        output_path=config["output_path"],
        upload=True
    )
    
    # Example search
    print("\n" + "="*50)
    print("Testing search functionality:")
    results = pipeline.search_similar("county government appointments", limit=3)
    for i, result in enumerate(results, 1):
        print(f"\n{i}. {result['title']} (Score: {result['score']:.3f})")
        print(f"   {result['content']}")

if __name__ == "__main__":
    main()