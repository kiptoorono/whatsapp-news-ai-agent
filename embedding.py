import json
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# Path to your articles JSON file
input_path = r"C:\Users\Rono\Desktop\Ai agent trial\peopledaily_articles.json"
output_path = r"C:\Users\Rono\Desktop\Ai agent trial\peopledaily_articles_embedded.json"

# Load articles
with open(input_path, "r", encoding="utf-8") as f:
    articles = json.load(f)

# Load embedding model
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

embedded_articles = []
for article in tqdm(articles, desc="Embedding articles"):
    text = f"{article['title']}\n{article['content']}"
    embedding = model.encode(text, show_progress_bar=False).tolist()
    embedded_articles.append({
        "title": article["title"],
        "url": article["url"],
        "date": article["date"],
        "category": article.get("category"),
        "embedding": embedding,
        "content": article.get("content", "")
    })

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(embedded_articles, f, ensure_ascii=False, indent=2)

print(f"Embeddings generated and saved to {output_path}!")
