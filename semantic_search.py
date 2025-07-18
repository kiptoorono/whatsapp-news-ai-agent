import json
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# Load embedded articles
with open(r"C:\Users\Rono\Desktop\Ai agent trial\peopledaily_articles_embedded.json", "r", encoding="utf-8") as f:
    articles = json.load(f)

# Load the same embedding model
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def search(query, top_k=5):
    # Embed the query
    query_emb = model.encode(query)
    # Stack all article embeddings into a matrix
    article_embs = np.array([a["embedding"] for a in articles])
    # Compute cosine similarities
    sims = cosine_similarity([query_emb], article_embs)[0]
    # Get top_k indices
    top_indices = sims.argsort()[-top_k:][::-1]
    # Print results
    print(f"\nTop {top_k} results for: '{query}'\n")
    for idx in top_indices:
        art = articles[idx]
        print(f"Title: {art['title']}")
        print(f"URL: {art['url']}")
        print(f"Category: {art.get('category')}")           
        print(f"Date: {art['date']}")
        print(f"Score: {sims[idx]:.3f}")
        print("-" * 60)

if __name__ == "__main__":
    while True:
        q = input("\nEnter your search query (or 'exit' to quit): ")
        if q.lower() == "exit":
            break
        search(q) 