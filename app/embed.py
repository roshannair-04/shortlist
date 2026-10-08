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
    # One inference at a time, one thread, small batches: on Render's 512 MB free tier,
    # parallel requests each holding their own attention buffers got the process OOM-killed.
    # ponytail: serialises embedding; fine at this traffic, use a bigger instance to parallelise.
    with _lock:
        if _model is None:
            from fastembed import TextEmbedding

            _model = TextEmbedding(MODEL, cache_dir=os.getenv("FASTEMBED_CACHE", ".models"), threads=1)
        vecs = np.array(list(_model.embed(list(texts), batch_size=16)), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


if __name__ == "__main__":  # used by the Dockerfile to bake the model into the image
    print(embed(["warm up"]).shape)
