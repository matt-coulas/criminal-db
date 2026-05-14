"""Embedding helpers.

The model is lazy-loaded so importing :mod:`criminal_db.cli` does not pull in
``sentence-transformers`` (a heavy dependency) until you actually run a
command that needs it.  This keeps ``criminal-db init`` / ``parse`` /
``search --type fts`` fast and dependency-light.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from . import config


class Embedder:
    """Thin wrapper around a ``sentence-transformers`` model.

    Parameters
    ----------
    model_name:
        HuggingFace model id.  Defaults to :data:`config.EMBEDDING_MODEL`.
    expected_dim:
        Optional sanity-check; ``encode`` raises if the model output dim does
        not match the configured embedding dimension, since that would mean
        the SQLite ``vec0`` table is shaped wrong.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        *,
        expected_dim: Optional[int] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        self.model_name = model_name or config.EMBEDDING_MODEL
        self.expected_dim = (
            expected_dim if expected_dim is not None else config.EMBEDDING_DIM
        )
        self.cache_dir = cache_dir or str(config.EMBEDDING_CACHE_DIR)
        self._model = None  # lazy

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - import guard
                raise RuntimeError(
                    "sentence-transformers is not installed. "
                    "Install it with `pip install criminal-db[embed]`."
                ) from exc
            # Prefer the local cache so we don't hit the Hub on every CLI
            # invocation.  Fall back to a normal load if the model isn't
            # cached yet.
            try:
                self._model = SentenceTransformer(
                    self.model_name,
                    cache_folder=self.cache_dir,
                    local_files_only=True,
                )
            except (OSError, ValueError):
                self._model = SentenceTransformer(
                    self.model_name, cache_folder=self.cache_dir
                )
            # ``get_sentence_embedding_dimension`` was renamed to
            # ``get_embedding_dimension`` in newer releases; support both.
            getter = getattr(
                self._model,
                "get_embedding_dimension",
                getattr(self._model, "get_sentence_embedding_dimension", None),
            )
            dim = getter() if callable(getter) else None
            if dim is not None and dim != self.expected_dim:
                raise RuntimeError(
                    f"Embedding model {self.model_name!r} produces {dim}-d vectors "
                    f"but config.EMBEDDING_DIM={self.expected_dim}. "
                    "Recreate the database with the correct dimension or "
                    "set CRIMINAL_DB_EMBEDDING_DIM accordingly."
                )
        return self._model

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: Optional[int] = None,
        normalize: bool = True,
    ) -> list[list[float]]:
        """Encode ``texts`` and return one Python list per input."""
        if not texts:
            return []
        model = self._load()
        size = batch_size or config.EMBEDDING_BATCH_SIZE
        # ``convert_to_numpy=True`` keeps memory predictable; we convert at the
        # boundary into plain Python lists so the rest of the pipeline never
        # depends on numpy types reaching sqlite.
        vectors = model.encode(
            list(texts),
            batch_size=size,
            normalize_embeddings=normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [vec.tolist() for vec in vectors]

    def encode_one(self, text: str, *, normalize: bool = True) -> list[float]:
        return self.encode([text], normalize=normalize)[0]


def chunked(items: Sequence, n: int) -> Iterable[Sequence]:
    """Yield successive ``n``-sized chunks from ``items``."""
    n = max(1, int(n))
    for i in range(0, len(items), n):
        yield items[i : i + n]
