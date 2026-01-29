import json
from typing import List, Dict, Any
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, VectorParams, Distance
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NewsEmbedder:
    def __init__(self, 
                 model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
                 qdrant_host: str = "localhost",
                 qdrant_port: int = 6333,
                 collection_name: str = "news_articles"):
        self.model = SentenceTransformer(model_name)
        self.client = QdrantClient(host=qdrant_host, port=qdrant_port)
        self.collection_name = collection_name

    def create_collection(self, vector_size: int):
        """Create Qdrant collection if it doesn't exist."""
        if self.collection_name not in [c.name for c in self.client.get_collections().collections]:
            self.client.recreate_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
            )
            logger.info(f"Created collection '{self.collection_name}' with vector size {vector_size}")

    def embed_and_upload(self, articles: List[Dict[str, Any]], batch_size: int = 32):
        texts = [f"{a.get('title', '')}\n{a.get('content', '')}" for a in articles]
        logger.info(f"Embedding {len(texts)} articles...")
        embeddings = self.model.encode(texts, show_progress_bar=True, batch_size=batch_size)
        self.create_collection(vector_size=len(embeddings[0]))

        points = []
        for idx, (article, vector) in enumerate(zip(articles, embeddings)):
            points.append(PointStruct(
                id=idx,
                vector=vector.tolist(),
                payload={
                    "title": article.get("title", ""),
                    "url": article.get("url", ""),
                    "date": article.get("date", ""),
                    "category": article.get("category", ""),
                    "content": article.get("content", "")
                }
            ))
        logger.info(f"Uploading {len(points)} points to Qdrant...")
        self.client.upsert(collection_name=self.collection_name, points=points)
        logger.info("Upload complete.")

if __name__ == "__main__":
    # Load your JSON
    with open("C:/Users/Rono/Desktop/Ai agent trial/peopledaily_articles.json", "r", encoding="utf-8") as f:
        articles = json.load(f)
    embedder = NewsEmbedder()
    embedder.embed_and_upload(articles)