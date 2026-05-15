"""
Test TVPL Parser — Parse HTML mẫu thành ParsedLegalDocument.

Chạy: uv run pytest tests/test_crawler/test_tvpl_parser.py -v

QUAN TRỌNG: HTML mẫu ở đây là giả lập.
Sau bước Recon (Ngày 0), bạn cần cập nhật với HTML thực từ TVPL.
"""

import pytest
from crawler.parsers.tvpl_parser import TVPLParser, ParsedArticle, ParsedLegalDocument


# === HTML mẫu giả lập cấu trúc TVPL ===

SAMPLE_HTML = """
<html>
<head><title>Bộ luật Lao động</title></head>
<body>
<h1 class="title-vb">BỘ LUẬT LAO ĐỘNG</h1>
<div class="so-hieu">45/2019/QH14</div>
<div class="co-quan-ban-hanh">Quốc hội</div>
<div class="ngay-ban-hanh">20/11/2019</div>
<div class="ngay-hieu-luc">01/01/2021</div>
<div class="trang-thai">Còn hiệu lực</div>

<div id="toanvancontent">

CHƯƠNG I
NHỮNG QUY ĐỊNH CHUNG

Điều 1. Phạm vi điều chỉnh
Bộ luật này quy định tiêu chuẩn lao động; quyền, nghĩa vụ, trách nhiệm
của người lao động, người sử dụng lao động, tổ chức đại diện người lao động
tại cơ sở, tổ chức đại diện người sử dụng lao động trong quan hệ lao động
và các quan hệ khác liên quan trực tiếp đến quan hệ lao động; quản lý nhà
nước về lao động.

Điều 2. Đối tượng áp dụng
1. Người lao động, người học nghề, người tập nghề và người làm việc không
có quan hệ lao động.
2. Người sử dụng lao động.
3. Người lao động nước ngoài làm việc tại Việt Nam.

CHƯƠNG VI
TIỀN LƯƠNG

Điều 90. Tiền lương
1. Tiền lương là số tiền mà người sử dụng lao động trả cho người lao động
theo thỏa thuận để thực hiện công việc, bao gồm mức lương theo công việc
hoặc chức danh, phụ cấp lương và các khoản bổ sung khác.
2. Mức lương theo công việc hoặc chức danh không được thấp hơn mức lương
tối thiểu.
3. Người sử dụng lao động phải bảo đảm trả lương bình đẳng, không phân
biệt giới tính đối với người lao động làm công việc có giá trị như nhau.

Điều 91. Mức lương tối thiểu
1. Mức lương tối thiểu là mức lương thấp nhất được trả cho người lao động
làm công việc giản đơn nhất trong điều kiện lao động bình thường nhằm bảo
đảm mức sống tối thiểu của người lao động và gia đình họ, phù hợp với điều
kiện phát triển kinh tế - xã hội.
2. Mức lương tối thiểu được xác lập theo vùng, ấn định theo tháng, giờ.
3. Mức lương tối thiểu được điều chỉnh dựa trên mức sống tối thiểu của
người lao động và gia đình họ; tương quan giữa mức lương tối thiểu và mức
lương trên thị trường; chỉ số giá tiêu dùng, tốc độ tăng trưởng kinh tế.

</div>
</body>
</html>
"""

SAMPLE_URL = "https://thuvienphapluat.vn/van-ban/lao-dong/bo-luat-lao-dong-2019-333670.aspx"

# HTML trống — không phải trang văn bản
EMPTY_HTML = "<html><body><h1>404 Not Found</h1></body></html>"

# HTML có content ngắn
SHORT_CONTENT_HTML = """
<html><body>
<h1 class="title-vb">Test</h1>
<div id="toanvancontent">Ngắn quá.</div>
</body></html>
"""


class TestParsedArticle:
    """Test dataclass ParsedArticle."""

    def test_create_article(self):
        article = ParsedArticle(
            article_number=90,
            article_title="Tiền lương",
            clauses=[{"number": 1, "text": "Tiền lương là...", "points": []}],
            raw_text="1. Tiền lương là...",
        )
        assert article.article_number == 90
        assert article.article_title == "Tiền lương"
        assert len(article.clauses) == 1


class TestParsedLegalDocument:
    """Test dataclass ParsedLegalDocument."""

    def test_create_empty_doc(self):
        doc = ParsedLegalDocument()
        assert doc.title == ""
        assert doc.total_articles == 0
        assert doc.status == "unknown"


class TestTVPLParser:
    """Test TVPLParser với HTML mẫu."""

    def setup_method(self):
        """Tạo parser instance cho mỗi test."""
        self.parser = TVPLParser()

    # --- Test parse() chính ---

    def test_parse_returns_document(self):
        """parse() phải trả về ParsedLegalDocument."""
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        assert isinstance(doc, ParsedLegalDocument)

    def test_parse_empty_html_returns_none(self):
        """HTML không phải trang VB → trả None."""
        doc = self.parser.parse(EMPTY_HTML, SAMPLE_URL)
        assert doc is None

    def test_parse_short_content_returns_none(self):
        """Content quá ngắn (<500 chars) → trả None."""
        doc = self.parser.parse(SHORT_CONTENT_HTML, SAMPLE_URL)
        assert doc is None

    # --- Test extract metadata ---

    def test_extract_title(self):
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        assert "LAO ĐỘNG" in doc.title.upper()

    def test_extract_doc_number(self):
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        assert doc.doc_number == "45/2019/QH14"

    def test_extract_source_id(self):
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        assert doc.source_id == "333670"

    def test_extract_source_url(self):
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        assert doc.source_url == SAMPLE_URL

    def test_classify_doc_type(self):
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        assert doc.doc_type == "bo_luat"

    def test_extract_issuer(self):
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        assert doc.issuer == "Quốc hội"

    def test_extract_status(self):
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        assert doc.status == "con_hieu_luc"

    # --- Test parse cấu trúc ---

    def test_parse_chapters(self):
        """Phải parse được ít nhất 2 chương."""
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        assert len(doc.chapters) >= 2

    def test_parse_articles(self):
        """Phải parse được ít nhất 4 điều (1, 2, 90, 91)."""
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        assert doc.total_articles >= 4

    def test_parse_article_90(self):
        """Điều 90 phải có 3 khoản."""
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        art90 = next((a for a in doc.articles if a.article_number == 90), None)
        assert art90 is not None
        assert art90.article_title.startswith("Tiền lương")
        assert len(art90.clauses) == 3

    def test_parse_article_without_clauses(self):
        """Điều 1 không có khoản → treated as 1 clause."""
        doc = self.parser.parse(SAMPLE_HTML, SAMPLE_URL)
        assert doc is not None
        art1 = next((a for a in doc.articles if a.article_number == 1), None)
        assert art1 is not None
        # Điều không có khoản → 1 clause với number=None
        assert len(art1.clauses) >= 1

    # --- Test clean text ---

    def test_clean_text_normalizes_unicode(self):
        """_clean_text phải normalize Unicode NFC."""
        # "ă" có thể là 1 char (NFC) hoặc 2 chars (NFD: a + combining breve)
        import unicodedata
        nfd = unicodedata.normalize("NFD", "ă")  # 2 chars
        result = self.parser._clean_text(nfd)
        assert len(result) == 1  # NFC: 1 char

    def test_clean_text_removes_extra_blanks(self):
        """Bỏ multiple blank lines."""
        result = self.parser._clean_text("line1\n\n\n\n\nline2")
        assert result == "line1\n\nline2"

    # --- Test classify doc type ---

    def test_classify_bo_luat(self):
        assert self.parser._classify_doc_type("Bộ luật Lao động", "") == "bo_luat"

    def test_classify_luat(self):
        assert self.parser._classify_doc_type("Luật Doanh nghiệp", "") == "luat"

    def test_classify_nghi_dinh(self):
        assert self.parser._classify_doc_type("Nghị định", "01/2024/NĐ-CP") == "nghi_dinh"

    def test_classify_thong_tu(self):
        assert self.parser._classify_doc_type("Thông tư", "01/2024/TT-BTC") == "thong_tu"
