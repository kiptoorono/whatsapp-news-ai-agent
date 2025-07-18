import json
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
import requests
from openai import OpenAI

# Qdrant connection (local)
client = QdrantClient(host="localhost", port=6333)
collection_name = "peopledaily_articles"

# Load embedding model
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

# --- SambaNova API client setup ---
SAMBA_API_KEY = "4cbd0c7f-db95-46fa-bdaa-586cd6ec9d24"  # Replace with your actual SambaNova API key
client_samba = OpenAI(
    base_url="https://api.sambanova.ai/v1",
    api_key=SAMBA_API_KEY,
)

def summarize_with_sambanova(text):
    prompt = (
        "Summarize the following news article in exactly 2 sentences. "
        "Be factual, neutral, and avoid speculation or opinion. "
        "Do not add information that is not present in the article.\n\n"
        f"{text}"
    )
    try:
        response = client_samba.chat.completions.create(
            model="Meta-Llama-3.1-405B-Instruct",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("SambaNova API error:", e)
        return "[SambaNova API error or quota exceeded]"

def search_qdrant_and_summarize(query, top_k=3):
    query_vector = model.encode(query).tolist()
    hits = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=top_k,
        with_payload=True
    )
    results = []
    for hit in hits:
        payload = hit.payload
        content = payload.get("content", "")
        if content:
            summary = summarize_with_sambanova(content)
        else:
            summary = "[No content available]"
        results.append(f"Title: {payload['title']}\nSummary: {summary}\nURL: {payload['url']}\n")
    return "\n".join(results)
