"""
Embedder — Embed chunks thành vectors bằng multilingual-e5-large.

Model: intfloat/multilingual-e5-large
- 1024 dimensions
- Hiểu tiếng Việt tốt nhất trong các multilingual models
- Prefix: "passage: " cho documents, "query: " cho search queries

Usage:
    embedder = Embedder()
    vectors = embedder.embed_chunks(chunks)
    query_vec = embedder.embed_query("lương tối thiểu vùng 1")
"""

import logging
from typing import Optional

import numpy as np
from tqdm import tqdm

from .chunker import Chunk
from ...config import settings

logger = logging.getLogger(__name__)

# Lazy load model để tiết kiệm RAM khi không cần
_model = None


def _load_model():
    """Lazy load embedding model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        logger.info(f"[Embedder] Loading model: {settings.embedding_model}")
        _model = SentenceTransformer(settings.embedding_model)
        logger.info(
            f"[Embedder] Model loaded. "
            f"Dim={_model.get_embedding_dimension()}"
        )
    return _model


class Embedder:
    """
    Embed text thành vectors với multilingual-e5-large.

    Lưu ý quan trọng:
    - Documents cần prefix "passage: "
    - Queries cần prefix "query: "
    - Vectors được L2 normalize trước khi trả về
    """

    def __init__(self):
        self.model = _load_model()
        self.dim = self.model.get_embedding_dimension()
        self.batch_size = settings.embedding_batch_size

    def embed_chunks(
        self,
        chunks: list[Chunk],
        show_progress: bool = True,
    ) -> np.ndarray:
        """
        Embed danh sách chunks → numpy array of vectors.

        Dùng full_context (breadcrumb + text) để embed — cho kết quả tốt hơn
        vì model hiểu context (VB nào, chương nào, điều nào).

        Args:
            chunks: List[Chunk] từ chunker
            show_progress: Hiện progress bar

        Returns:
            np.ndarray shape (len(chunks), 1024)
        """
        # Prefix "passage: " cho documents
        texts = [f"passage: {chunk.full_context}" for chunk in chunks]

        logger.info(f"[Embedder] Embedding {len(texts)} chunks (batch_size={self.batch_size})")

        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=show_progress,
            normalize_embeddings=True,  # L2 normalize
        )

        logger.info(f"[Embedder] Done. Shape: {embeddings.shape}")
        return embeddings

    def embed_query(self, query: str) -> np.ndarray:
        """
        Embed 1 search query → vector.

        Args:
            query: Câu hỏi người dùng (VD: "lương tối thiểu vùng 1 là bao nhiêu")

        Returns:
            np.ndarray shape (1024,)
        """
        text = f"query: {query}"
        embedding = self.model.encode(
            [text],
            normalize_embeddings=True,
        )
        return embedding[0]

    def embed_texts(
        self,
        texts: list[str],
        prefix: str = "passage: ",
        show_progress: bool = False,
    ) -> np.ndarray:
        """
        Embed arbitrary texts (low-level method).

        Args:
            texts: List of strings
            prefix: "passage: " hoặc "query: "
            show_progress: Hiện progress bar

        Returns:
            np.ndarray shape (len(texts), 1024)
        """
        prefixed = [f"{prefix}{t}" for t in texts]
        return self.model.encode(
            prefixed,
            batch_size=self.batch_size,
            show_progress_bar=show_progress,
            normalize_embeddings=True,
        )
