import os
import openai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

openai_api_key = os.environ.get("OPENAI_API_KEY")

def get_embedding(text: str) -> list[float]:
    """Generates a 768-dimensional embedding for the given text using OpenAI text-embedding-3-small."""
    if not text or not openai_api_key:
        return None
        
    try:
        client = openai.OpenAI(api_key=openai_api_key)
        # Limit text length to avoid token limits (~8192 tokens max, 1 char ~ 4 token-ish, so 15000 chars is safe)
        result = client.embeddings.create(
            model="text-embedding-3-small",
            input=text[:15000],
            dimensions=768
        )
        return result.data[0].embedding
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return None

def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Generates embeddings for a batch of texts using OpenAI."""
    if not texts or not openai_api_key:
        return [None] * len(texts)
    
    try:
        client = openai.OpenAI(api_key=openai_api_key)
        truncated_texts = [t[:15000] for t in texts]
        
        # OpenAI supports batching directly
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=truncated_texts,
            dimensions=768
        )
        # Sort embeddings by their index in the response data
        embeddings_sorted = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in embeddings_sorted]
    except Exception as e:
        print(f"Error generating batch embeddings: {e}")
        return [None] * len(texts)
