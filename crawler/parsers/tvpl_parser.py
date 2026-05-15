"""
TVPL Parser — Parse văn bản pháp luật từ thuvienphapluat.vn.

Cấu trúc văn bản pháp luật Việt Nam:
    Văn bản (VD: Bộ luật Lao động 2019)
    └── Phần (hiếm)
        └── Chương (CHƯƠNG I, II, ...)
            └── Mục (Mục 1, 2, ...)
                └── Điều (Điều 1, 2, ...)
                    └── Khoản (1., 2., 3., ...)
                        └── Điểm (a), b), c), ...)

Parser này extract từ HTML theo cấu trúc trên.

CSS Selectors đã verified ngày 2026-05-15 qua recon trực tiếp:
- Title: <h1> (không class)
- Content: div#divContentDoc.cldivContentDocVn hoặc div.content1
- Metadata: nằm trong <td> elements (table rows)
- Số hiệu: extract từ <title> hoặc <h1> bằng regex
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup


@dataclass
class ParsedArticle:
    """
    Một điều luật đã được parse.

    Attributes:
        article_number: Số điều (VD: 90)
        article_title: Tên điều (VD: "Tiền lương")
        clauses: Danh sách khoản [{number, text, points}]
        raw_text: Text gốc chưa parse
    """
    article_number: int
    article_title: str
    clauses: list[dict] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class ParsedLegalDocument:
    """
    Văn bản pháp luật đã được parse đầy đủ.

    Attributes:
        doc_id: ID nội bộ (UUID, gán bởi storage)
        source_id: ID trên TVPL (extract từ URL)
        source_url: URL gốc trên TVPL
        title: Tiêu đề (VD: "Bộ luật Lao động 2019")
        doc_number: Số hiệu (VD: "45/2019/QH14")
        doc_type: Loại VB (bo_luat, luat, nghi_dinh, thong_tu, ...)
        issuer: Cơ quan ban hành (VD: "Quốc hội")
        issue_date: Ngày ban hành
        effective_date: Ngày có hiệu lực
        status: Trạng thái (con_hieu_luc, het_hieu_luc, unknown)
        chapters: Danh sách chương [{number, title}]
        articles: Danh sách điều [ParsedArticle]
        total_articles: Tổng số điều
        raw_html: HTML gốc (lưu để reparse)
    """
    doc_id: str = ""
    source_id: str = ""
    source_url: str = ""
    title: str = ""
    doc_number: str = ""
    doc_type: str = ""
    issuer: str = ""
    issue_date: str = ""
    effective_date: str = ""
    status: str = "unknown"
    chapters: list[dict] = field(default_factory=list)
    articles: list[ParsedArticle] = field(default_factory=list)
    total_articles: int = 0
    raw_html: str = ""


class TVPLParser:
    """
    Parser cho thuvienphapluat.vn.

    CSS Selectors đã verified 2026-05-15:
    - Title: <h1> tag (không có class riêng)
    - Content: #divContentDoc, .content1, #tab1.contentDoc
    - Metadata: trong <td> elements (table-based layout)
    - Status: <td class="text-red"> cho "Còn hiệu lực"

    Usage:
        parser = TVPLParser()
        doc = parser.parse(html_string, url)
        if doc:
            print(f"Parsed: {doc.title} — {doc.total_articles} điều")
    """

    # CSS Selectors — VERIFIED 2026-05-15 trên HTML thực tế
    SELECTORS = {
        # Title: h1 tag (thường là tag đầu tiên)
        "title": "h1",
        # Content area chứa toàn bộ nội dung VB
        "content_area": (
            "#divContentDoc, "            # div#divContentDoc.cldivContentDocVn
            ".content1, "                 # div.content1
            "#tab1.contentDoc, "           # div#tab1.contentDoc
            "#ctl00_Content_ThongTinVB_pnlDocContent"  # panel nội dung
        ),
    }

    # === Regex Patterns cho cấu trúc pháp luật VN ===

    # Chương: "CHƯƠNG I", "CHƯƠNG IV", "CHƯƠNG 1"
    CHAPTER_PATTERN = re.compile(
        r"CHƯƠNG\s+([IVXLCDM]+|\d+)[.\s]*\n?(.*?)(?=CHƯƠNG|\Z)",
        re.IGNORECASE | re.DOTALL
    )

    # Mục: "MỤC 1", "MỤC 2"
    SECTION_PATTERN = re.compile(
        r"MỤC\s+(\d+)[.\s]*(.*?)(?=MỤC|\Z)",
        re.IGNORECASE | re.DOTALL
    )

    # Điều: "Điều 90. Tiền lương"
    ARTICLE_PATTERN = re.compile(
        r"Điều\s+(\d+)[.\s]*(.*?)(?=Điều\s+\d+|\Z)",
        re.IGNORECASE | re.DOTALL
    )

    # Khoản: "1. Nội dung...", "2. Nội dung..."
    CLAUSE_PATTERN = re.compile(
        r"^(\d+)\.\s+(.+?)(?=^\d+\.|\Z)",
        re.MULTILINE | re.DOTALL
    )

    # Điểm: "a) Nội dung...", "b) Nội dung..."
    POINT_PATTERN = re.compile(
        r"^([a-zđ])\)\s+(.+?)(?=^[a-zđ]\)|\Z)",
        re.MULTILINE | re.DOTALL
    )

    # Regex extract số hiệu từ title hoặc h1
    DOC_NUMBER_PATTERN = re.compile(
        r"(?:số\s+)?(\d+/\d{4}/[A-ZĐ\-]+\d*)",
        re.IGNORECASE
    )

    def parse(self, html: str, url: str) -> Optional[ParsedLegalDocument]:
        """
        Parse HTML của một văn bản pháp luật trên TVPL.

        Args:
            html: HTML string từ response
            url: URL gốc (để extract source_id)

        Returns:
            ParsedLegalDocument nếu parse thành công
            None nếu không phải trang văn bản hoặc parse thất bại
        """
        soup = BeautifulSoup(html, "html.parser")

        # Extract metadata
        title = self._extract_title(soup)
        if not title:
            return None  # Không phải trang văn bản

        doc_number = self._extract_doc_number(soup, title)
        content_text = self._extract_content(soup)
        if not content_text:
            return None

        # Parse cấu trúc phân cấp
        chapters = self._parse_chapters(content_text)
        articles = self._parse_articles(content_text)

        return ParsedLegalDocument(
            doc_id="",  # Sẽ được gán bởi storage layer
            source_id=self._extract_source_id(url),
            source_url=url,
            title=title,
            doc_number=doc_number,
            doc_type=self._classify_doc_type(title, doc_number),
            issuer=self._extract_issuer(soup),
            issue_date=self._extract_date(soup, "ban_hanh"),
            effective_date=self._extract_date(soup, "hieu_luc"),
            status=self._extract_status(soup),
            chapters=chapters,
            articles=articles,
            total_articles=len(articles),
            raw_html="",  # Không lưu raw HTML trong object — quá lớn
        )

    # === Private Methods: Extract từ HTML ===

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """
        Extract tiêu đề văn bản từ HTML.

        Thử lần lượt:
        1. <h1> tag (verified: <h1>Bộ luật lao động 2019 số 45/2019/QH14...</h1>)
        2. <title> tag (fallback)
        """
        # Thử h1 trước
        h1 = soup.find("h1")
        if h1:
            text = h1.get_text(strip=True)
            # Loại bỏ phần "áp dụng 2025 mới nhất" ở cuối nếu có
            text = re.sub(r"\s*áp dụng\s+\d{4}.*$", "", text)
            if text:
                return text

        # Fallback: <title> tag
        title_tag = soup.find("title")
        if title_tag:
            text = title_tag.get_text(strip=True)
            # Loại bỏ suffix "mới nhất"
            text = re.sub(r"\s*mới nhất.*$", "", text)
            return text

        return ""

    def _extract_doc_number(self, soup: BeautifulSoup, title: str = "") -> str:
        """
        Extract số hiệu VB (VD: 45/2019/QH14).

        Verified: TVPL không có element riêng cho số hiệu.
        Số hiệu nằm trong:
        1. <h1> text (VD: "Bộ luật lao động 2019 số 45/2019/QH14 áp dụng 2025")
        2. <title> tag
        3. Tìm trong các <td> elements
        """
        # Tìm trong title (h1 hoặc title tag)
        search_text = title
        if not search_text:
            title_tag = soup.find("title")
            if title_tag:
                search_text = title_tag.get_text(strip=True)

        if search_text:
            match = self.DOC_NUMBER_PATTERN.search(search_text)
            if match:
                return match.group(1)

        # Fallback: tìm trong các <td> elements
        for td in soup.find_all("td"):
            text = td.get_text(strip=True)
            match = self.DOC_NUMBER_PATTERN.search(text)
            if match and len(text) < 50:  # Chỉ lấy td ngắn
                return match.group(1)

        return ""

    def _extract_content(self, soup: BeautifulSoup) -> str:
        """
        Extract nội dung chính, loại bỏ menu/sidebar/footer/ads.
        Chỉ trả về text nếu đủ dài (>500 chars) — tránh lấy nhầm snippet.
        """
        for selector in self.SELECTORS["content_area"].split(", "):
            selector = selector.strip()
            el = soup.select_one(selector)
            if el:
                # Xóa elements không cần thiết
                for tag in el.select("script, style, .ads, .sidebar, nav, .lqhlTip, .divltrDanChieu"):
                    tag.decompose()
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 500:
                    return self._clean_text(text)
        return ""

    def _clean_text(self, text: str) -> str:
        """
        Làm sạch text tiếng Việt từ HTML.

        Xử lý:
        - Unicode normalize NFC (chuẩn cho tiếng Việt — tổ hợp dấu thành 1 ký tự)
        - Bỏ multiple blank lines
        - Bỏ spaces thừa
        - Bỏ ký tự control không in được
        """
        text = unicodedata.normalize("NFC", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        return text.strip()

    # === Private Methods: Parse cấu trúc ===

    def _parse_chapters(self, text: str) -> list[dict]:
        """Parse cấu trúc chương từ text."""
        chapters = []
        for match in self.CHAPTER_PATTERN.finditer(text):
            chapters.append({
                "number": match.group(1),
                "title": match.group(2).strip().split("\n")[0],
            })
        return chapters

    def _parse_articles(self, text: str) -> list[ParsedArticle]:
        """Parse tất cả điều luật từ text."""
        articles = []
        for match in self.ARTICLE_PATTERN.finditer(text):
            article_num = int(match.group(1))
            article_content = match.group(2).strip()

            # Split title và nội dung
            lines = article_content.split("\n", 1)
            article_title = lines[0].strip() if lines else ""
            article_body = lines[1].strip() if len(lines) > 1 else article_content

            clauses = self._parse_clauses(article_body)
            articles.append(ParsedArticle(
                article_number=article_num,
                article_title=article_title,
                clauses=clauses,
                raw_text=article_content,
            ))
        return articles

    def _parse_clauses(self, text: str) -> list[dict]:
        """Parse các khoản (1., 2., ...) trong một điều."""
        matches = list(self.CLAUSE_PATTERN.finditer(text))

        if not matches:
            # Điều không có khoản → treat cả điều là 1 clause
            return [{"number": None, "text": text.strip(), "points": []}]

        clauses = []
        for match in matches:
            clause_text = match.group(2).strip()
            points = self._parse_points(clause_text)
            clauses.append({
                "number": int(match.group(1)),
                "text": clause_text,
                "points": points,
            })
        return clauses

    def _parse_points(self, text: str) -> list[dict]:
        """Parse các điểm (a), b), c),...) trong khoản."""
        points = []
        for match in self.POINT_PATTERN.finditer(text):
            points.append({
                "letter": match.group(1),
                "text": match.group(2).strip(),
            })
        return points

    # === Private Methods: Classify & Extract Metadata ===

    def _classify_doc_type(self, title: str, doc_number: str) -> str:
        """
        Phân loại loại văn bản dựa trên title và số hiệu.

        Returns: "bo_luat", "luat", "nghi_dinh", "thong_tu", "quyet_dinh", "khac"
        """
        title_lower = title.lower()
        if "bộ luật" in title_lower:
            return "bo_luat"
        if "luật" in title_lower:
            return "luat"
        if "/nđ-cp" in doc_number.lower() or "nghị định" in title_lower:
            return "nghi_dinh"
        if "/tt-" in doc_number.lower() or "thông tư" in title_lower:
            return "thong_tu"
        if "quyết định" in title_lower:
            return "quyet_dinh"
        return "khac"

    def _extract_source_id(self, url: str) -> str:
        """Extract ID văn bản từ URL TVPL: /van-ban/ten-123456.aspx → 123456."""
        match = re.search(r"-(\d+)\.aspx$", url)
        return match.group(1) if match else ""

    def _extract_issuer(self, soup: BeautifulSoup) -> str:
        """
        Extract cơ quan ban hành.

        Verified: TVPL dùng table rows, tìm td chứa text "Quốc hội", "Chính phủ", etc.
        """
        # Tìm text trong các td elements
        issuer_keywords = [
            "Quốc hội", "Chính phủ", "Thủ tướng",
            "Bộ", "UBND", "Ủy ban",
        ]
        for td in soup.find_all("td"):
            text = td.get_text(strip=True)
            for keyword in issuer_keywords:
                if keyword in text and len(text) < 100:
                    return text
        return ""

    def _extract_date(self, soup: BeautifulSoup, date_type: str) -> str:
        """
        Extract ngày ban hành hoặc ngày hiệu lực.

        Verified: TVPL dùng table rows, tìm td chứa ngày dd/mm/yyyy.

        Args:
            date_type: "ban_hanh" hoặc "hieu_luc"
        """
        date_pattern = re.compile(r"\d{2}/\d{2}/\d{4}")

        # Tìm tất cả td có ngày
        dates_found = []
        for td in soup.find_all("td"):
            text = td.get_text(strip=True)
            match = date_pattern.search(text)
            if match and len(text) < 30:
                dates_found.append(match.group())

        if not dates_found:
            return ""

        # ban_hanh = ngày đầu tiên, hieu_luc = ngày thứ hai
        if date_type == "ban_hanh" and len(dates_found) >= 1:
            return dates_found[0]
        if date_type == "hieu_luc" and len(dates_found) >= 2:
            return dates_found[1]

        return dates_found[0] if dates_found else ""

    def _extract_status(self, soup: BeautifulSoup) -> str:
        """
        Extract trạng thái hiệu lực.

        Verified: TVPL dùng <td class="text-red">Còn hiệu lực</td>
        """
        # Tìm td có class text-red (trạng thái)
        el = soup.select_one("td.text-red")
        if el:
            text = el.get_text(strip=True).lower()
            if "còn hiệu lực" in text:
                return "con_hieu_luc"
            if "hết hiệu lực" in text:
                return "het_hieu_luc"
            return text  # Trạng thái khác

        # Fallback: tìm text "còn hiệu lực" / "hết hiệu lực" trong bất kỳ td nào
        for td in soup.find_all("td"):
            text = td.get_text(strip=True).lower()
            if "còn hiệu lực" in text:
                return "con_hieu_luc"
            if "hết hiệu lực" in text:
                return "het_hieu_luc"

        return "unknown"
