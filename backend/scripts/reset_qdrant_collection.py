"""Delete and recreate the Qdrant collection at the configured embedding dimension.

Use after switching from OpenAI 1536-d embeddings to local FastEmbed 768-d
(BAAI/bge-base-en-v1.5). Existing points are incompatible and must be re-indexed.

Run from backend/:
  python scripts/reset_qdrant_collection.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.indexing.qdrant_index import QdrantIndex  # noqa: E402


def _collection_info(client, name: str) -> dict:
    names = {c.name for c in client.get_collections().collections}
    if name not in names:
        return {"exists": False, "name": name}
    info = client.get_collection(name)
    vectors = getattr(info.config.params, "vectors", None)
    size = getattr(vectors, "size", None) if vectors is not None else None
    distance = getattr(vectors, "distance", None) if vectors is not None else None
    return {
        "exists": True,
        "name": name,
        "points_count": getattr(info, "points_count", None),
        "vector_size": size,
        "distance": str(distance) if distance is not None else None,
        "status": str(getattr(info, "status", "")),
    }


def main() -> int:
    settings = get_settings()
    index = QdrantIndex(settings)
    client = index._get_client()
    name = index.collection

    before = _collection_info(client, name)
    print("=== BEFORE ===")
    for key, value in before.items():
        print(f"  {key}: {value}")
    print(f"  settings.embedding_dimensions: {settings.embedding_dimensions}")
    print(f"  settings.embedding_provider: {settings.embedding_provider}")
    print(f"  settings.embedding_model: {settings.embedding_model}")

    if before["exists"]:
        print(f"\nDeleting collection '{name}' ...")
        client.delete_collection(collection_name=name)
        print("Deleted.")
    else:
        print(f"\nCollection '{name}' did not exist — nothing to delete.")

    print(f"\nRecreating collection at {index.dimensions}-d ...")
    index.ensure_collection()

    after = _collection_info(client, name)
    print("\n=== AFTER ===")
    for key, value in after.items():
        print(f"  {key}: {value}")

    if after.get("vector_size") not in (None, settings.embedding_dimensions):
        print(
            "\nWARNING: collection vector_size "
            f"{after.get('vector_size')} != settings.embedding_dimensions "
            f"{settings.embedding_dimensions}"
        )
        return 1

    print("\nDone. Re-run indexing/embedding for documents to repopulate vectors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
