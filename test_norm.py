import numpy as np
from backend.app.services.embedding_provider import EmbeddingProvider

provider = EmbeddingProvider()
vec = provider.embed_single("test sentence")
norm = np.linalg.norm(vec)
print(f"Vector shape: {vec.shape}")
print(f"Vector norm: {norm}")
print(f"First 5 elements: {vec[:5]}")
