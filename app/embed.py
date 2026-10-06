"""Sentence embeddings via fastembed (ONNX). Same all-MiniLM-L6-v2 model as before,
without torch: ~100 MB of RAM instead of ~500 MB, which matters on Render's free tier."""
import os
import threading

import numpy as np

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_model = None
_lock = threading.Lock()


def embed(texts):
    """Return an (n, 384) array of unit-length vectors, so a dot product is cosine similarity."""
    global _model
    with _lock:
        if _model is None:
            from fastembed import TextEmbedding

            _model = TextEmbedding(MODEL, cache_dir=os.getenv("FASTEMBED_CACHE", ".models"))
    vecs = np.array(list(_model.embed(list(texts))), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


if __name__ == "__main__":  # used by the Dockerfile to bake the model into the image
    print(embed(["warm up"]).shape)
