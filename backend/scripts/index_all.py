"""
Index All — CLI script chạy full ingestion pipeline.

Chạy:
    uv run python -m backend.scripts.index_all
    uv run python -m backend.scripts.index_all --max 5
"""

import argparse
import asyncio
import logging
import sys
import io

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


async def main(max_docs=None):
    from backend.app.services.ingestion.index_job import index_from_crawl_db

    print("\n🏛️  Legal RAG — Index Pipeline")
    print("=" * 50)
    print(f"  Max docs: {max_docs or 'All'}")
    print("=" * 50)

    result = await index_from_crawl_db(max_docs=max_docs)

    if result:
        print(f"\n✅ Index completed!")
        print(f"  Documents: {result['documents']}")
        print(f"  Chunks:    {result['chunks']}")
        print(f"  Qdrant:    {result['points_upserted']} points upserted")
        print(f"  Total:     {result['collection_total']} points in collection")
    else:
        print("\n❌ Index failed — check logs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index crawled documents into Qdrant")
    parser.add_argument("--max", type=int, default=None, help="Max documents to index")
    args = parser.parse_args()

    asyncio.run(main(max_docs=args.max))
