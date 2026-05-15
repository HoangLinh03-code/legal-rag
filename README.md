# 🏛️ Legal RAG — Hệ thống Hỏi đáp Pháp luật Việt Nam bằng AI

> **Crawl tự động · Vector Search · Claude AI · Trích dẫn điều khoản cụ thể**
>
> Hệ thống tự động thu thập toàn bộ corpus pháp luật Việt Nam từ [thuvienphapluat.vn](https://thuvienphapluat.vn),
> index bằng vector embeddings, và cho phép hỏi đáp bằng ngôn ngữ tự nhiên có trích dẫn
> chính xác đến từng Điều/Khoản/Điểm.

---

## 📋 Mục lục

- [Vấn đề & Giải pháp](#-vấn-đề--giải-pháp)
- [Kiến trúc hệ thống](#-kiến-trúc-hệ-thống)
- [Tech Stack](#-tech-stack)
- [Cấu trúc thư mục](#-cấu-trúc-thư-mục)
- [Quick Start](#-quick-start)
- [Hướng dẫn chi tiết](#-hướng-dẫn-chi-tiết)
  - [1. Setup môi trường](#1-setup-môi-trường)
  - [2. Chạy Crawler](#2-chạy-crawler)
  - [3. Chạy Ingestion Pipeline](#3-chạy-ingestion-pipeline)
  - [4. Chạy Backend API](#4-chạy-backend-api)
- [Output & Dữ liệu lưu trữ](#-output--dữ-liệu-lưu-trữ)
- [API Reference](#-api-reference)
- [Cấu hình & Biến môi trường](#-cấu-hình--biến-môi-trường)
- [Chiến lược Anti-ban](#-chiến-lược-anti-ban)
- [Trạng thái hiện tại](#-trạng-thái-hiện-tại)
- [Roadmap](#-roadmap)

---

## 🎯 Vấn đề & Giải pháp

### Vấn đề

Người Việt Nam gặp khó khăn khi tiếp cận pháp luật vì:

- Không biết **văn bản nào** áp dụng cho tình huống của mình
- Ngôn ngữ pháp lý **phức tạp**, phân cấp nhiều tầng (Chương → Mục → Điều → Khoản → Điểm)
- Các trang pháp luật hiện tại chỉ hỗ trợ **tìm kiếm keyword** — không hiểu câu hỏi tự nhiên
- Phải biết trước số hiệu văn bản mới tìm được

### Giải pháp

```
User hỏi: "Thời gian thử việc tối đa là bao nhiêu?"
                        ↓
           Vector Search + BM25 Hybrid
                        ↓
    Tìm: Điều 25, BLLĐ 2019 — "Thời gian thử việc"
                        ↓
       Claude AI tổng hợp + trích dẫn chính xác
                        ↓
    "Theo Điều 25, Khoản 1, Bộ luật Lao động 2019
     (45/2019/QH14), thời gian thử việc không quá
     180 ngày với chức vụ quản lý doanh nghiệp..."
     [Xem nguồn: thuvienphapluat.vn →]
```

**Thay vì yêu cầu user upload PDF**, hệ thống tự động crawl và cập nhật toàn bộ corpus
pháp luật Việt Nam — người dùng chỉ cần hỏi bằng tiếng Việt tự nhiên.

---

## 🏗️ Kiến trúc hệ thống

```
╔══════════════════════════════════════════════════════════════════════╗
║                        DATA COLLECTION LAYER                        ║
║                                                                      ║
║  thuvienphapluat.vn ──┐                                              ║
║                        ├──► Stealth Crawler ──► raw_html/{hash}.html ║
║  luatvietnam.vn ───────┘         │                                   ║
║                                  │  (httpx + Playwright fallback)    ║
║                                  ▼                                   ║
║                           HTML Parser                                ║
║                     (extract Chương/Điều/Khoản)                      ║
║                                  │                                   ║
║                                  ▼                                   ║
║                    crawl_db/crawl_index.json                         ║
║                    crawl_db/{hash}.json       (structured docs)      ║
╚══════════════════════════════════════════════════════════════════════╝
                               │
                               ▼
╔══════════════════════════════════════════════════════════════════════╗
║                       INGESTION PIPELINE                            ║
║                                                                      ║
║  ParsedLegalDocument                                                 ║
║         │                                                            ║
║         ▼                                                            ║
║     Chunker ──► [Chunk: "Điều 90 Khoản 1 | Tiền lương là..."]       ║
║         │       breadcrumb context + metadata                        ║
║         ▼                                                            ║
║     Embedder ──► multilingual-e5-large (1024-dim)                   ║
║         │        prefix: "passage: [context]\ntext"                  ║
║         ▼                                                            ║
║      Qdrant ──► Collection: legal_docs                               ║
║                 Payload indexes: doc_type, status, dieu_so...        ║
╚══════════════════════════════════════════════════════════════════════╝
                               │
                               ▼
╔══════════════════════════════════════════════════════════════════════╗
║                      RETRIEVAL & GENERATION                         ║
║                                                                      ║
║  User Query                                                          ║
║      │                                                               ║
║      ├──► Dense Search  (Qdrant cosine similarity)   ─┐             ║
║      │    embed "query: {question}"                    │             ║
║      │                                                 ├──► RRF      ║
║      └──► Sparse Search (BM25 keyword matching)      ─┘   Reranker  ║
║                                                            │         ║
║                                                            ▼         ║
║                                                     Top-K Chunks     ║
║                                                            │         ║
║                                                            ▼         ║
║                                              Claude API (claude-sonnet)║
║                                              System prompt + RAG context║
║                                                            │         ║
║                                                            ▼         ║
║                                             Answer + Citations []     ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Data Flow chi tiết

```
[CRAWL]
TVPL URL list
    → StealthHTTPClient.get(url)        # rate-limited, cookie-managed
    → BanDetector.check(response)       # detect Cloudflare/429/403
    → PlaywrightStealthClient (fallback) # bypass Cloudflare nếu cần
    → CrawlStorage.save_raw_html()      # disk: raw_html/{hash}.html
    → TVPLParser.parse()                # extract structured document
    → CrawlStorage.save_document()      # disk: crawl_db/{hash}.json

[INDEX]
crawl_db/*.json
    → TVPLParser.parse(html, url)       # re-parse từ HTML gốc
    → create_chunks(doc)                # clause-level chunking
    → Embedder.embed_chunks()           # batch encode với e5-large
    → Qdrant.upsert(points)            # batch 100 points/request

[QUERY]  (Tuần 2–3)
user_question
    → embed_query("query: {q}")
    → qdrant.search() + bm25.search()
    → reciprocal_rank_fusion(results)
    → cross_encoder.rerank(top20→top5)
    → claude.messages.create(context)
    → stream response + citations
```

---

## 🛠️ Tech Stack

| Layer | Technology | Lý do chọn |
|-------|-----------|------------|
| **Crawler HTTP** | `httpx[http2]` | Async, HTTP/2, cookie jar, không overhead như requests |
| **Crawler JS** | `Playwright` | Bypass Cloudflare, render JavaScript, human simulation |
| **HTML Parser** | `BeautifulSoup4 + lxml` | Robust với HTML lỗi, CSS selectors nhanh |
| **Rate Limiting** | Token Bucket (custom) | Jitter ngẫu nhiên, anti-pattern detection |
| **Embedding Model** | `intfloat/multilingual-e5-large` | Hiểu tiếng Việt tốt nhất, 1024-dim |
| **Vector DB** | `Qdrant` | Payload filtering mạnh, HNSW index, tự host |
| **Keyword Search** | `rank-bm25` | BM25 cho tiếng Việt, bổ sung semantic search |
| **LLM** | `Claude claude-sonnet-4-20250514` | API, context window lớn, Vietnamese tốt |
| **Backend** | `FastAPI + asyncpg` | Async native, Pydantic validation, SSE streaming |
| **Database** | `PostgreSQL + SQLAlchemy` | Lưu metadata, conversation history, tracking |
| **Frontend** | `Next.js 14 + Tailwind` | App router, streaming support, Shadcn/ui |
| **Package Mgr** | `uv` | 10-100x nhanh hơn pip, lockfile deterministic |
| **Infra** | `Docker Compose` | PostgreSQL + Qdrant local/production |

---

## 📁 Cấu trúc thư mục

```
legal-rag/
│
├── crawler/                          # Module crawl dữ liệu
│   ├── __init__.py
│   ├── __main__.py                   # CLI entry point
│   ├── run_crawl.py                  # Logic crawl chính
│   ├── recon.py                      # Phân tích HTML trước khi crawl
│   │
│   ├── core/                         # Thư viện lõi crawler
│   │   ├── http_client.py            # Stealth HTTP client (UA rotation, cookies)
│   │   ├── playwright_client.py      # Playwright bypass Cloudflare
│   │   ├── rate_limiter.py           # Token bucket + jitter + crawl hours
│   │   ├── ban_detector.py           # Phát hiện & xử lý block/ban
│   │   ├── proxy_pool.py             # Round-robin proxy rotation
│   │   └── storage.py                # Lưu HTML + metadata (disk + JSON)
│   │
│   ├── parsers/                      # HTML Parsers
│   │   └── tvpl_parser.py            # Parse thuvienphapluat.vn
│   │                                 # → extract Chương/Điều/Khoản
│   └── spiders/
│       └── tvpl_spider.py            # Spider: discover URLs + crawl loop
│
├── backend/                          # FastAPI backend
│   ├── app/
│   │   ├── main.py                   # FastAPI app, CORS, lifespan
│   │   ├── config.py                 # Pydantic settings từ .env
│   │   ├── database.py               # Async SQLAlchemy engine + session
│   │   │
│   │   ├── api/
│   │   │   ├── admin.py              # GET /admin/stats, POST /admin/index/trigger
│   │   │   ├── chat.py               # POST /chat (Tuần 3)
│   │   │   ├── search.py             # GET /search (Tuần 2)
│   │   │   └── documents.py          # GET /documents (Tuần 3)
│   │   │
│   │   ├── models/
│   │   │   └── legal_document.py     # ORM: LegalDocument, DocumentChunk,
│   │   │                             #       CrawledURL, Conversation, Message
│   │   ├── schemas/                  # Pydantic request/response schemas
│   │   │
│   │   └── services/
│   │       └── ingestion/
│   │           ├── chunker.py        # create_chunks() — clause-level chunking
│   │           ├── embedder.py       # Embedder — multilingual-e5-large
│   │           └── index_job.py      # Full pipeline: parse→chunk→embed→qdrant
│   │
│   └── scripts/
│       └── index_all.py              # CLI: chạy index pipeline
│
├── frontend/                         # Next.js UI (Tuần 4)
│
├── tests/
│   └── test_crawler/
│       ├── test_tvpl_parser.py       # Unit tests parser
│       ├── test_rate_limiter.py      # Unit tests rate limiter
│       └── test_crawl_integration.py # Integration tests (real HTTP)
│
├── raw_html/                         # ← GITIGNORED: Raw HTML files
│   └── {url_hash}.html               #   Backup để reparse khi cần
│
├── crawl_db/                         # ← GITIGNORED: Crawl metadata
│   ├── crawl_index.json              #   url_hash → metadata mapping
│   └── {url_hash}.json               #   Structured document (parsed)
│
├── docker-compose.yml                # PostgreSQL + Qdrant
├── pyproject.toml                    # Dependencies (uv)
├── uv.lock                           # Lockfile deterministic
├── .env.example                      # Template biến môi trường
└── .gitignore
```

---

## ⚡ Quick Start

> **3 bước để chạy hệ thống cơ bản (crawl + index):**

```bash
# 1. Clone và setup
git clone https://github.com/your-username/legal-rag.git
cd legal-rag
cp .env.example .env                  # Điền ANTHROPIC_API_KEY vào .env

# 2. Khởi động infrastructure
docker compose up -d                  # PostgreSQL :5432 + Qdrant :6333

# 3. Cài dependencies
uv sync                               # Đọc uv.lock, cài đúng version

# 4. Crawl + Index (test nhỏ 5 văn bản)
uv run python -m crawler crawl --max 5
uv run python -m backend.scripts.index_all --max 5

# 5. Chạy API
uv run uvicorn backend.app.main:app --reload --port 8000
# → http://localhost:8000/docs
```

---

## 📖 Hướng dẫn chi tiết

### 1. Setup môi trường

#### Yêu cầu hệ thống

| Phần mềm | Version | Ghi chú |
|----------|---------|---------|
| Python | ≥ 3.12 | Type hints mới nhất |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | ≥ 24 | Chạy PostgreSQL + Qdrant |
| GPU (tùy chọn) | CUDA 12.x | Tăng tốc embedding 5-10x |

#### Cài đặt step-by-step

```bash
# --- Bước 1: Clone project ---
git clone https://github.com/your-username/legal-rag.git
cd legal-rag

# --- Bước 2: Tạo .env ---
cp .env.example .env
# Mở .env, điền:
#   ANTHROPIC_API_KEY=sk-ant-...
#   DATABASE_URL=postgresql+asyncpg://legal_rag:legal_rag_dev@localhost:5432/legal_rag
#   (Các giá trị khác có thể giữ mặc định)

# --- Bước 3: Khởi động Database & Qdrant ---
docker compose up -d
# Kiểm tra services đã healthy:
docker compose ps
# Expected output:
#   legal_rag_postgres   running   (healthy)
#   legal_rag_qdrant     running   (healthy)

# --- Bước 4: Cài Python dependencies ---
uv sync
# Nếu có NVIDIA GPU (CUDA 12.x), torch CUDA đã được config sẵn trong pyproject.toml

# Kiểm tra GPU (optional):
uv run python check_gpu.py
# Expected: "CUDA available: True", "GPU: NVIDIA GeForce RTX..."

# --- Bước 5: Cài Playwright browsers ---
uv run playwright install chromium
# Chỉ cần chromium — đủ để bypass Cloudflare

# --- Bước 6: Kiểm tra setup ---
uv run uvicorn backend.app.main:app --port 8000 &
curl http://localhost:8000/health
# Expected: {"status":"ok","qdrant":"connected","docs_indexed":0}
```

---

### 2. Chạy Crawler

Crawler có 3 chế độ: `recon`, `crawl`, và `status`.

#### Chế độ Recon (khuyến nghị chạy trước)

Phân tích HTML từ TVPL để verify CSS selectors trước khi crawl hàng loạt:

```bash
uv run python -m crawler recon
```

**Output:**
```
🔍 RECON — Phân tích thuvienphapluat.vn
══════════════════════════════════════════════════════════════════════

RECON: https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/...
Status: 200
Content-Length: 185,432 chars
Cloudflare Challenge: KHÔNG ✓

--- CSS Selector Analysis ---
  ✓ title [h1]: 'Bộ luật lao động 2019 số 45/2019/QH14 áp dụng 2025'
  ✓ content_area [#divContentDoc]: 'CHƯƠNG I NHỮNG QUY ĐỊNH CHUNG...'

--- Parse Result ---
  ✓ Title: Bộ luật Lao động 2019
  ✓ Doc Number: 45/2019/QH14
  ✓ Type: bo_luat
  ✓ Issuer: Quốc hội
  ✓ Status: con_hieu_luc
  ✓ Chapters: 17
  ✓ Articles: 220

Saved HTML: raw_html/a1b2c3d4...html
```

#### Chế độ Crawl

```bash
# Test nhỏ (5 văn bản) — chạy trước để verify
uv run python -m crawler crawl --max 5

# Crawl Bộ luật + Luật (P1)
uv run python -m crawler crawl --type bo-luat --max 50
uv run python -m crawler crawl --type luat --max 200

# Crawl tất cả loại (P1 + P2)
uv run python -m crawler crawl --type bo-luat,luat,nghi-dinh --max 500

# Nếu bị Cloudflare → dùng Playwright (chậm hơn ~10x nhưng bypass được)
uv run python -m crawler crawl --playwright --max 10

# Re-parse tất cả HTML đã lưu (khi cập nhật parser)
uv run python -m crawler reparse
```

**Output crawl:**
```
🏛️  Legal RAG Crawler
════════════════════════════════════════════════════════════
  Types: ['bo-luat', 'luat']
  Max docs: 50
  Engine: httpx
  Started: 09:15:30
════════════════════════════════════════════════════════════

📋 Total URLs to crawl: 50

  ✓ [1/50] Bộ luật Lao động 2019 (220 articles)
  ⏳ Delay: 14s
  ✓ [2/50] Bộ luật Dân sự 2015 (689 articles)
  ⏳ Delay: 17s
  ...
  ⏳ Long break: 92s   ← Nghỉ dài sau 15 requests
  ✓ [16/50] Luật Doanh nghiệp 2020 (218 articles)
  ...

════════════════════════════════════════════════════════════
📊 Crawl Summary
════════════════════════════════════════════════════════════
  Duration: 1247s (20.8 min)
  Success:    48
  Skipped:    0
  Cloudflare: 1
  Parse Error: 1
  Error:      0

  Storage: {'total_crawled': 48, 'total_parsed': 47, 'pending_parse': 1}
```

#### Xem trạng thái crawl

```bash
uv run python -m crawler status
```

```
📊 Crawl Status
════════════════════════════
  Total crawled:  247
  Total parsed:   244
  Pending parse:  3
```

---

### 3. Chạy Ingestion Pipeline

Sau khi crawl xong, chạy pipeline để embed và index vào Qdrant:

```bash
# Index tất cả documents đã crawl
uv run python -m backend.scripts.index_all

# Chỉ index N documents đầu tiên (test)
uv run python -m backend.scripts.index_all --max 10

# Hoặc trigger qua API (chạy background)
curl -X POST http://localhost:8000/admin/index/trigger
curl -X POST "http://localhost:8000/admin/index/trigger?max_docs=50"
```

**Output index pipeline:**
```
🏛️  Legal RAG — Index Pipeline
══════════════════════════════════════════════════════
  Max docs: All
══════════════════════════════════════════════════════

09:30:15 [INFO] Found 247 entries in crawl_db
09:30:15 [INFO] [Embedder] Loading model: intfloat/multilingual-e5-large
09:30:28 [INFO] [Embedder] Model loaded. Dim=1024
09:30:28 [INFO] [Index] [1] Bộ luật Lao động 2019 → 312 chunks
09:30:28 [INFO] [Index] [2] Bộ luật Dân sự 2015 → 941 chunks
...
09:30:45 [INFO] [Index] Total: 247 docs → 28,450 chunks
09:30:45 [INFO] [Embedder] Embedding 28,450 chunks (batch_size=64)
Batches: 100%|████████████████| 445/445 [08:23<00:00, 0.88it/s]
09:39:08 [INFO] [Qdrant] Upserted 100/28450 points
09:39:09 [INFO] [Qdrant] Upserted 200/28450 points
...
09:52:17 [INFO] [Qdrant] Upserted 28450/28450 points
09:52:18 [INFO] [Index] Done! Indexed 28450 points. Collection total: 28450 points

✅ Index completed!
  Documents: 247
  Chunks:    28,450
  Qdrant:    28,450 points upserted
```

**Kiểm tra collection Qdrant:**
```bash
# Mở Qdrant Web UI
open http://localhost:6333/dashboard
# → Collection "legal_docs" → xem points, payload, vector
```

---

### 4. Chạy Backend API

```bash
# Development (với hot reload)
uv run uvicorn backend.app.main:app --reload --port 8000

# Production
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

**Kiểm tra API:**
```bash
# Health check
curl http://localhost:8000/health
# {"status":"ok","version":"0.2.0","docs_indexed":28450,"qdrant":"connected"}

# Thống kê admin
curl http://localhost:8000/admin/stats
# {"total_documents":247,"total_chunks":28450,"qdrant_points":28450,...}

# Danh sách văn bản đã crawl
curl "http://localhost:8000/admin/documents?limit=10"

# Swagger UI (interactive docs)
open http://localhost:8000/docs
```

---

## 💾 Output & Dữ liệu lưu trữ

### Sơ đồ lưu trữ

```
legal-rag/
│
├── raw_html/                          # Disk — HTML gốc (backup)
│   ├── a1b2c3d4e5f6...html           # Bộ luật Lao động 2019
│   ├── b2c3d4e5f6a1...html           # Bộ luật Dân sự 2015
│   └── ...                           # ~247 files, ~500MB total
│
├── crawl_db/                          # Disk — Metadata + Parsed docs
│   ├── crawl_index.json              # Index chính: url_hash → metadata
│   ├── a1b2c3d4e5f6...json           # Parsed document (cấu trúc Chương/Điều)
│   └── ...                           # ~247 JSON files
│
└── [Docker Volumes]
    ├── postgres_data/                 # PostgreSQL: ORM models
    │   ├── legal_documents            # Metadata văn bản
    │   ├── document_chunks            # Chunks với qdrant_id
    │   ├── crawled_urls               # Tracking URL status
    │   ├── conversations              # Chat history
    │   └── messages                   # Message history
    │
    └── qdrant_data/                   # Qdrant: vectors + payload
        └── legal_docs/               # Collection
            ├── vectors (1024-dim)    # Embeddings
            └── payload               # Metadata cho filtering
```

### Format dữ liệu

#### `crawl_db/crawl_index.json`

```json
{
  "a1b2c3d4e5f67890abcdef1234567890": {
    "url": "https://thuvienphapluat.vn/van-ban/Lao-dong.../Bo-Luat-lao-dong-2019-333670.aspx",
    "crawled_at": "2026-05-15T09:15:32.451234",
    "html_path": "raw_html/a1b2c3d4e5f67890abcdef1234567890.html",
    "parsed": true,
    "title": "Bộ luật Lao động 2019",
    "doc_number": "45/2019/QH14"
  }
}
```

#### `crawl_db/{hash}.json` — Structured Document

```json
{
  "doc_id": "a1b2c3d4e5f67890abcdef1234567890",
  "source_url": "https://thuvienphapluat.vn/...",
  "title": "Bộ luật Lao động 2019",
  "doc_number": "45/2019/QH14",
  "doc_type": "bo_luat",
  "issuer": "Quốc hội",
  "issue_date": "20/11/2019",
  "effective_date": "01/01/2021",
  "status": "con_hieu_luc",
  "total_articles": 220,
  "chapters": [
    {"number": "I", "title": "Những quy định chung"},
    {"number": "VI", "title": "Tiền lương"}
  ],
  "articles": [
    {
      "number": 90,
      "title": "Tiền lương",
      "clauses": [
        {
          "number": 1,
          "text": "Tiền lương là số tiền mà người sử dụng lao động trả...",
          "points": []
        },
        {
          "number": 2,
          "text": "Mức lương theo công việc hoặc chức danh không được thấp hơn...",
          "points": []
        }
      ]
    }
  ]
}
```

#### Qdrant Point Payload

```json
{
  "text": "Tiền lương là số tiền mà người sử dụng lao động trả...",
  "full_context": "[Bộ luật Lao động 2019 | Chương VI: Tiền lương | Điều 90: Tiền lương | Khoản 1]\nTiền lương là số tiền...",
  "source_url": "https://thuvienphapluat.vn/van-ban/.../Bo-Luat-lao-dong-2019-333670.aspx",
  "source_site": "thuvienphapluat.vn",
  "van_ban": "Bộ luật Lao động 2019",
  "doc_number": "45/2019/QH14",
  "doc_type": "bo_luat",
  "issue_date": "20/11/2019",
  "status": "con_hieu_luc",
  "issuer": "Quốc hội",
  "chuong_so": "VI",
  "chuong_ten": "Tiền lương",
  "dieu_so": 90,
  "dieu_ten": "Tiền lương",
  "khoan_so": 1,
  "chunk_type": "clause",
  "char_count": 287
}
```

#### Chunking Strategy

```
ParsedLegalDocument (220 articles)
    │
    ▼
Điều 90: Tiền lương
    ├── Khoản 1 → Chunk #1  (287 chars)
    ├── Khoản 2 → Chunk #2  (156 chars)
    └── Khoản 3 → Chunk #3  (198 chars)

Điều 91: Mức lương tối thiểu
    ├── Khoản 1 → Chunk #4  (312 chars)
    ├── Khoản 2 → Chunk #5  (89 chars)
    └── Khoản 3 → Chunk #6  (245 chars)    ← dài → sliding window

Khoản quá dài (> 2000 chars) → Sliding Window:
    ├── Window 1 → Chunk #N    (2000 chars)
    ├── Window 2 → Chunk #N+1  (2000 chars, overlap 200 chars)
    └── Window 3 → Chunk #N+2  (1200 chars)
```

---

## 📡 API Reference

### Health & Admin

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET` | `/health` | Kiểm tra trạng thái hệ thống và Qdrant |
| `GET` | `/admin/stats` | Thống kê: số VB, chunks, Qdrant points |
| `GET` | `/admin/documents` | Danh sách văn bản đã crawl (paginated) |
| `POST` | `/admin/index/trigger` | Trigger index pipeline (chạy background) |

#### GET `/health`

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "version": "0.2.0",
  "docs_indexed": 28450,
  "qdrant": "connected"
}
```

#### GET `/admin/stats`

```bash
curl http://localhost:8000/admin/stats
```

```json
{
  "total_documents": 247,
  "total_chunks": 28450,
  "qdrant_points": 28450,
  "last_crawl": "2026-05-15T09:15:32.451234",
  "raw_html_files": 247
}
```

#### GET `/admin/documents?limit=10&offset=0`

```bash
curl "http://localhost:8000/admin/documents?limit=5"
```

```json
[
  {
    "url_hash": "a1b2c3d4...",
    "url": "https://thuvienphapluat.vn/...",
    "crawled_at": "2026-05-15T09:15:32",
    "status": "crawled"
  }
]
```

#### POST `/admin/index/trigger`

```bash
# Index tất cả
curl -X POST http://localhost:8000/admin/index/trigger

# Index tối đa 50 docs
curl -X POST "http://localhost:8000/admin/index/trigger?max_docs=50"
```

```json
{"status": "started", "documents": 0, "chunks": 0, "points_upserted": 0}
```

### Chat & Search *(Đang phát triển — Tuần 2-3)*

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `POST` | `/chat` | Hỏi đáp RAG với streaming |
| `GET` | `/search` | Tìm kiếm hybrid (dense + BM25) |
| `GET` | `/documents` | List văn bản với filter |
| `GET` | `/documents/{id}/articles` | Điều khoản trong văn bản |

---

## ⚙️ Cấu hình & Biến môi trường

Sao chép `.env.example` thành `.env` và điền giá trị:

```bash
# ── Database ──────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://legal_rag:legal_rag_dev@localhost:5432/legal_rag

# ── Qdrant ────────────────────────────────────────────
QDRANT_HOST=localhost
QDRANT_PORT=6333

# ── Claude API ────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-api03-...   # Bắt buộc cho chat (Tuần 3)

# ── Crawl Settings ────────────────────────────────────
CRAWL_DELAY_MIN=10       # Delay tối thiểu giữa requests (giây)
CRAWL_DELAY_MAX=25       # Delay tối đa (giây) — jitter ngẫu nhiên
CRAWL_HOURS_START=8      # Chỉ crawl từ 8h sáng
CRAWL_HOURS_END=22       # Đến 22h tối (không crawl ban đêm)

# ── Proxy (tùy chọn) ──────────────────────────────────
PROXY_URL=               # http://user:pass@proxy:8080 (để trống = không dùng)
```

### Cấu hình embedding (trong `config.py`)

```python
embedding_model: str = "intfloat/multilingual-e5-large"  # 1024-dim
embedding_dim: int = 1024
embedding_batch_size: int = 64   # Tăng nếu có GPU nhiều VRAM
```

---

## 🛡️ Chiến lược Anti-ban

Hệ thống implements 6 lớp bảo vệ để crawl không bị block:

```
Layer 1: Rate Limiting
  → Token Bucket Algorithm (không phải sleep() cố định)
  → Jitter ngẫu nhiên 10-25s mỗi request
  → Nghỉ dài 1-3 phút sau mỗi 15 requests
  → Không crawl ngoài 8h-22h (giống giờ làm việc con người)

Layer 2: Identity Rotation
  → 5 User-Agent thực từ Chrome/Firefox/Edge Việt Nam
  → Rotate UA sau mỗi 10 requests
  → Session cookie được duy trì và cập nhật

Layer 3: Headers Authenticity
  → Accept-Language: vi-VN (traffic từ Việt Nam)
  → Sec-Fetch-* headers đầy đủ như Chrome thực
  → Referer header được set đúng

Layer 4: Behavior Simulation (Playwright)
  → Scroll trang từ từ như người thực
  → Random delay sau mỗi action
  → Viewport 1366x768 (phổ biến ở Việt Nam)
  → navigator.webdriver = undefined (ẩn automation)

Layer 5: Ban Detection & Recovery
  → 403 → rotate proxy ngay lập tức
  → 429 → sleep 30-40 phút
  → 503 → sleep 10-15 phút
  → Cloudflare JS challenge → chuyển sang Playwright
  → CAPTCHA → sleep 1-1.5 giờ
  → 3 ban liên tiếp → dừng hẳn, log cảnh báo

Layer 6: Proxy Pool (tùy chọn)
  → Round-robin rotation
  → Mark dead proxies, tự recover sau timeout
  → Ưu tiên IP từ Việt Nam (ít bị suspicious)
```

**Nguyên tắc cốt lõi:** Crawl **cực kỳ lịch sự** — 1 request mỗi 10-25 giây, chỉ giờ hành chính,
không burst, không concurrent với cùng domain. Mục tiêu là thu thập dữ liệu trong nhiều ngày/tuần,
không phải vài giờ.

---

## 🚦 Trạng thái hiện tại

### ✅ Đã hoàn thành (Tuần 0)

| Component | Status | Ghi chú |
|-----------|--------|---------|
| Project setup (uv, Docker, pyproject.toml) | ✅ Done | Python 3.12, CUDA support |
| `StealthHTTPClient` | ✅ Done | UA rotation, cookies, retry |
| `PlaywrightStealthClient` | ✅ Done | Bypass Cloudflare, human scroll |
| `TokenBucketRateLimiter` | ✅ Done | Jitter, crawl hours, page break |
| `BanDetector` | ✅ Done | 10 ban patterns, 7 recovery actions |
| `ProxyPool` | ✅ Done | Round-robin, mark dead |
| `CrawlStorage` (disk-based) | ✅ Done | JSON index + HTML files |
| `TVPLParser` | ✅ Done | Verified selectors 2026-05-15 |
| `TVPLSpider` | ✅ Done | discover + crawl loop |
| `Chunker` | ✅ Done | Clause-level + sliding window |
| `Embedder` | ✅ Done | multilingual-e5-large, batch |
| `IndexJob` | ✅ Done | Full pipeline, Qdrant upsert |
| `FastAPI` (basic) | ✅ Done | Health, Admin endpoints |
| Unit tests (parser, rate limiter) | ✅ Done | |

### 🚧 Đang phát triển (Tuần 1-3)

| Component | Status | ETA |
|-----------|--------|-----|
| PostgreSQL migration (từ JSON) | 🚧 In Progress | Tuần 1 |
| BM25 keyword search | ⬜ Todo | Tuần 2 |
| Hybrid search + RRF | ⬜ Todo | Tuần 2 |
| Cross-encoder reranker | ⬜ Todo | Tuần 2 |
| Claude RAG integration | ⬜ Todo | Tuần 3 |
| `/chat` API with streaming | ⬜ Todo | Tuần 3 |
| Citation verification | ⬜ Todo | Tuần 3 |
| Frontend Next.js | ⬜ Todo | Tuần 4 |
| Scheduled crawl (APScheduler) | ⬜ Todo | Tuần 5 |

---

## 🗺️ Roadmap

```
Tuần 0 (Hiện tại): ██████████ 100% — Crawl Infrastructure
  ✅ Crawler + Parser + Storage + Chunker + Embedder + Index

Tuần 1: ░░░░░░░░░░   0% — Foundation & Ingestion
  ⬜ PostgreSQL migration
  ⬜ Alembic migrations
  ⬜ Admin API hoàn chỉnh
  ⬜ Crawl scheduler (APScheduler)

Tuần 2: ░░░░░░░░░░   0% — Search Engine
  ⬜ BM25 index (rank-bm25 + underthesea tokenizer)
  ⬜ Hybrid search endpoint GET /search
  ⬜ Reciprocal Rank Fusion
  ⬜ Cross-encoder reranker (ms-marco-MiniLM)
  ⬜ Metadata filtering (doc_type, status, date range)

Tuần 3: ░░░░░░░░░░   0% — RAG & Chat API
  ⬜ Claude API integration với streaming
  ⬜ POST /chat với SSE streaming
  ⬜ Citation verification
  ⬜ Conversation history (multi-turn)
  ⬜ Query reformulation từ context

Tuần 4: ░░░░░░░░░░   0% — UI & Evaluation
  ⬜ Next.js frontend (chat + browse văn bản)
  ⬜ Citation cards với link TVPL
  ⬜ Evaluation: 30 test queries, Precision@5, MRR
  ⬜ Docker production build
  ⬜ Deploy lên VPS (DigitalOcean Singapore)

Tuần 5: ░░░░░░░░░░   0% — Production & Maintenance
  ⬜ Weekly scheduled crawl (phát hiện VB mới/hết hiệu lực)
  ⬜ Data quality audit
  ⬜ Monitoring (Grafana/Prometheus)
  ⬜ Backup PostgreSQL + Qdrant
```

---

## 🧪 Chạy Tests

```bash
# Unit tests (không cần network)
uv run pytest tests/ -v -m "not integration"

# Integration tests (cần internet — gửi request thực đến TVPL)
uv run pytest tests/ -v -m integration

# Chỉ test parser
uv run pytest tests/test_crawler/test_tvpl_parser.py -v

# Chỉ test rate limiter
uv run pytest tests/test_crawler/test_rate_limiter.py -v

# Test coverage
uv run pytest tests/ --cov=crawler --cov=backend --cov-report=html
open htmlcov/index.html
```

**Test nhanh chunker:**
```bash
# Cần có file raw_html/test_clean.html (chạy recon trước)
uv run python test_chunker_quick.py
```

---

## 🔧 Development

### Linting & Formatting

```bash
# Kiểm tra code style
uv run ruff check .

# Tự fix
uv run ruff check . --fix

# Type checking
uv run mypy backend/ crawler/ --ignore-missing-imports
```

### Re-parse HTML (khi cập nhật parser)

```bash
# Re-parse tất cả HTML đã lưu trong raw_html/
# (Không cần crawl lại — tiết kiệm bandwidth và tránh bị ban)
uv run python -m crawler reparse
```

### Xem logs Qdrant

```bash
docker compose logs qdrant -f
```

### Kết nối PostgreSQL

```bash
docker compose exec postgres psql -U legal_rag -d legal_rag
# Sau đó:
# \dt         — xem danh sách tables
# \d legal_documents  — xem schema
# SELECT COUNT(*) FROM legal_documents;
```

---

## ❓ Troubleshooting

### Cloudflare block khi crawl

```bash
# Triệu chứng: status "cloudflare" trong summary
# Giải pháp: dùng Playwright
uv run python -m crawler crawl --playwright --max 10

# Nếu vẫn bị: chờ 1-2 giờ rồi thử lại
# Hoặc: đổi IP (dùng proxy hoặc VPN)
```

### Parse thất bại (parse_error)

```bash
# TVPL có thể thay đổi HTML structure
# Bước 1: Chạy recon để phân tích lại
uv run python -m crawler recon

# Bước 2: Kiểm tra HTML đã lưu
# Xem raw_html/{hash}.html trong browser
# Tìm CSS selectors mới trong DevTools

# Bước 3: Cập nhật SELECTORS trong crawler/parsers/tvpl_parser.py
# Bước 4: Re-parse tất cả HTML đã lưu
uv run python -m crawler reparse
```

### Model embedding chậm (CPU)

```bash
# Kiểm tra CUDA
uv run python check_gpu.py

# Nếu không có GPU: giảm batch size
# Trong .env hoặc config.py:
# embedding_batch_size = 16   (mặc định 64)

# Thời gian ước tính:
#   CPU (Intel i7): ~10 phút / 1000 chunks
#   GPU (RTX 3050): ~1 phút / 1000 chunks
```

### Qdrant connection refused

```bash
# Kiểm tra container chạy không
docker compose ps

# Restart nếu cần
docker compose restart qdrant

# Xem logs
docker compose logs qdrant --tail=50
```

---

## 📄 License

MIT License — xem [LICENSE](LICENSE) file.

---

## 🙏 Credits

- **Dữ liệu:** [thuvienphapluat.vn](https://thuvienphapluat.vn) — Cơ sở dữ liệu pháp luật Việt Nam
- **Embedding:** [intfloat/multilingual-e5-large](https://huggingface.co/intfloat/multilingual-e5-large) — Microsoft
- **Vector DB:** [Qdrant](https://qdrant.tech) — Open source vector search engine
- **LLM:** [Claude](https://anthropic.com) — Anthropic

---

*README được cập nhật lần cuối: 2026-05-15 | Phiên bản: 0.2.0-alpha*