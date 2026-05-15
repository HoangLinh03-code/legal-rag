"""
Crawl Runner — Script chính để crawl dữ liệu pháp luật.

Chạy:
    # Recon trước (phân tích selectors)
    uv run python -m crawler recon

    # Crawl batch nhỏ (test 5 văn bản)
    uv run python -m crawler crawl --max 5

    # Crawl Bộ luật + Luật (P1)
    uv run python -m crawler crawl --type bo-luat --max 50

    # Xem status
    uv run python -m crawler status
"""

import argparse
import asyncio
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def cmd_recon(args):
    """Chạy recon để phân tích HTML."""
    from .recon import main as recon_main
    asyncio.run(recon_main())


def cmd_crawl(args):
    """Chạy crawl."""
    from .run_crawl import run_crawl
    asyncio.run(run_crawl(
        doc_types=args.type.split(",") if args.type else None,
        max_docs=args.max,
        use_playwright=args.playwright,
    ))


def cmd_status(args):
    """Xem trạng thái crawl."""
    from .core.storage import CrawlStorage
    storage = CrawlStorage(raw_dir="raw_html", db_dir="crawl_db")
    stats = storage.stats
    print(f"\n📊 Crawl Status")
    print(f"{'='*40}")
    print(f"  Total crawled:  {stats['total_crawled']}")
    print(f"  Total parsed:   {stats['total_parsed']}")
    print(f"  Pending parse:  {stats['pending_parse']}")
    print()


def cmd_reparse(args):
    """Re-parse tất cả HTML đã lưu (khi cập nhật parser)."""
    from .run_crawl import reparse_all
    asyncio.run(reparse_all())


def main():
    parser = argparse.ArgumentParser(
        prog="crawler",
        description="Legal RAG Crawler — Crawl dữ liệu pháp luật Việt Nam",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # recon
    sub_recon = subparsers.add_parser("recon", help="Phân tích cấu trúc HTML target sites")
    sub_recon.set_defaults(func=cmd_recon)

    # crawl
    sub_crawl = subparsers.add_parser("crawl", help="Crawl văn bản pháp luật")
    sub_crawl.add_argument("--type", type=str, default=None,
                           help="Loại VB: bo-luat,luat,nghi-dinh (phân cách bằng dấu phẩy)")
    sub_crawl.add_argument("--max", type=int, default=10,
                           help="Số VB tối đa (mặc định 10)")
    sub_crawl.add_argument("--playwright", action="store_true",
                           help="Dùng Playwright thay vì httpx")
    sub_crawl.set_defaults(func=cmd_crawl)

    # status
    sub_status = subparsers.add_parser("status", help="Xem trạng thái crawl")
    sub_status.set_defaults(func=cmd_status)

    # reparse
    sub_reparse = subparsers.add_parser("reparse", help="Re-parse tất cả HTML đã lưu")
    sub_reparse.set_defaults(func=cmd_reparse)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
