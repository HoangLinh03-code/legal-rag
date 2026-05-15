"""Test chunker nhanh."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
from crawler.parsers.tvpl_parser import TVPLParser
from backend.app.services.ingestion.chunker import create_chunks

parser = TVPLParser()
html = Path('raw_html/test_clean.html').read_text(encoding='utf-8')
url = 'https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/Bo-Luat-lao-dong-2019-333670.aspx'
doc = parser.parse(html, url)

chunks = create_chunks(doc)
print(f'Total chunks: {len(chunks)}')
print(f'Total articles: {doc.total_articles}')
avg = sum(c.char_count for c in chunks) / len(chunks)
print(f'Avg chars/chunk: {avg:.0f}')
print()

for i, c in enumerate(chunks[:3]):
    print(f'--- Chunk {i+1} ---')
    ct = c.metadata.get("chunk_type", "")
    ds = c.metadata.get("dieu_so", "")
    ks = c.metadata.get("khoan_so", "")
    print(f'  Type: {ct}')
    print(f'  Dieu: {ds}')
    print(f'  Khoan: {ks}')
    print(f'  Chars: {c.char_count}')
    print(f'  Context: {c.full_context[:200]}...')
    print()
