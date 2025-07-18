import json
from qdrant_client import QdrantClient
from qdrant_client.http import models
from tqdm import tqdm

# Path to your embedded articles
input_path = r"C:\Users\Rono\Desktop\Ai agent trial\peopledaily_articles_embedded.json"

# Qdrant connection (local)
client = QdrantClient(host="localhost", port=6333)

# Collection name
collection_name = "peopledaily_articles"

# Load embedded articles
with open(input_path, "r", encoding="utf-8") as f:
    articles = json.load(f)

# Get vector size from first embedding
vector_size = len(articles[0]["embedding"])

# Create collection if it doesn't exist
if collection_name not in [c.name for c in client.get_collections().collections]:
    client.recreate_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
    )

# Prepare points for upload
points = []
for idx, article in enumerate(tqdm(articles, desc="Preparing points")):
    points.append(
        models.PointStruct(
            id=idx,
            vector=article["embedding"],
            payload={
                "title": article["title"],
                "url": article["url"],
                "date": article["date"],
                "category": article.get("category"),
                "content": article.get("content", "")
            }
        )
    )

# Upload in batches
BATCH_SIZE = 256
for i in tqdm(range(0, len(points), BATCH_SIZE), desc="Uploading to Qdrant"):
    client.upsert(
        collection_name=collection_name,
        points=points[i:i+BATCH_SIZE]
    )

print("Upload complete!")
