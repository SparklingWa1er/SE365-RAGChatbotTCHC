"""Tool agent do dự án tự viết — tách khỏi mã thư viện kotaemon (giống rag/prompts.py).

Hiện có:
  - BraveSearchTool: tìm web qua Brave Search API, dùng làm FALLBACK khi corpus nội
    bộ không có tài liệu liên quan (thiết kế Corrective-RAG).

Được `app/libs/ktem/ktem/reasoning/react.py` import vào TOOL_REGISTRY.

Module chỉ phụ thuộc `requests` + `decouple` (nhẹ), an toàn để lib import sớm.
"""

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import AnyStr, Optional, Type
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from decouple import config
from pydantic import BaseModel, Field

from kotaemon.agents.tools.base import BaseTool
from kotaemon.base import Document, RetrievedDocument

logger = logging.getLogger(__name__)

# Tín hiệu DocSearchTool phát ra khi không có đoạn nào liên quan (sau relevance gate).
# Agent đọc chuỗi này để biết cần chuyển sang web_search. Giữ ở MỘT nơi để react.py
# và prompt dùng nhất quán.
NO_RELEVANT_DOC_MESSAGE = (
    "KHÔNG tìm thấy tài liệu liên quan trong cơ sở dữ liệu thủ tục hành chính nội bộ."
)

# Tín hiệu khi agent lặp lại y hệt một truy vấn đã tra (E2) — buộc đổi từ khoá thay vì
# phí phạm vòng lặp. DocSearchTool trả chuỗi này khi gặp Action Input trùng.
REPEATED_QUERY_MESSAGE = (
    "Bạn đã tra truy vấn này rồi (kết quả như các Observation trước). Hãy đổi từ khoá "
    "KHÁC HẲN, thử công cụ khác, hoặc kết luận nếu đã đủ thông tin."
)

# Nhãn gọn cho nguồn web (dùng làm file_name của web-doc). Pha synthesis nhận diện
# tiền tố 🌐 này để gắn ký hiệu trích dẫn riêng (xem rag/prompts.py:REACT_QA_CITATION_PROMPT)
# và phân biệt với nguồn corpus chính thống trong panel Information.
WEB_SOURCE_MARK = "🌐"

# Điểm relevance gán cho web-doc: đặt < ngưỡng cảnh báo corpus (CONTEXT_RELEVANT_WARNING_SCORE
# mặc định 0.3) là cố ý — web chưa thẩm định nên không nên tỏ ra "rất liên quan"; nhưng > 0
# để không bị relevance-gate loại nhầm. Đủ để hiển thị + sắp xếp trong panel nguồn.
WEB_DOC_SCORE = 0.2

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class ToolContext:
    """Tài nguyên request-scoped pipeline tiêm vào tool mỗi câu hỏi (mục A).

    Thay cho chuỗi `if tool_name == ...` gán thủ công retrievers/doc_sink/llm
    trong react.py:get_pipeline. Là plain class (không qua pydantic/theflow) để
    truyền tự do retriever, llm và list dùng chung.
    """

    def __init__(self, retrievers=None, llm=None, doc_sink=None):
        self.retrievers = retrievers if retrievers is not None else []
        self.llm = llm
        self.doc_sink = doc_sink


class CitableTool(BaseTool):
    """Base cho tool ReAct của dự án — gom 3 mục của khảo sát thiết kế:

    - A (Dependency Injection): `bind(ctx)` nhận tài nguyên request-scoped → tool
      tự lấy thứ mình cần, get_pipeline KHÔNG còn switch theo tên tool. Lớp con
      override `bind` khi cần thêm (vd DocSearchTool lấy thêm retrievers).
    - B (gom nguồn dùng chung): `emit(doc)` đẩy MỘT nguồn citable vào doc_sink,
      tự dedup theo doc_id → mỗi tool không phải tự lặp lại logic append/dedup.
    - C (metadata điều phối): `priority` quyết định thứ tự liệt kê tool trong
      prompt (nhỏ = ưu tiên trước). Hướng dẫn "khi nào dùng" đặt ở `description`
      của từng tool (slot chuẩn của ReAct) → prompt trung tâm không nhắc tên tool.
    """

    priority: int = 100
    doc_sink: Optional[list] = None

    def bind(self, ctx: "ToolContext") -> None:
        self.doc_sink = ctx.doc_sink

    def emit(self, doc) -> None:
        """Gom một nguồn citable cho pha synthesis; dedup theo doc_id (bỏ qua
        khi doc_sink chưa được gán = chế độ không gom)."""
        if self.doc_sink is None:
            return
        key = getattr(doc, "doc_id", None)
        if key is not None and any(
            getattr(d, "doc_id", None) == key for d in self.doc_sink
        ):
            return
        self.doc_sink.append(doc)


def _strip_html(text: str) -> str:
    """Brave trả description có thể kèm thẻ <strong> highlight — bỏ thẻ + unescape."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _fetch_page_text(url: str, max_chars: int) -> str:
    """Tải nội dung trang web rồi bóc text chính (bỏ script/style/nav...).

    Snippet của Brave thường THIẾU chi tiết cụ thể (địa chỉ/giờ làm việc/SĐT) — fetch
    trang để pha synthesis có dữ liệu thật mà trích dẫn. Lỗi mạng/parse -> trả "" (chỉ
    dùng snippet, không chặn agent). Cắt theo max_chars để không phình ngữ cảnh pha 2.
    """
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                )
            },
            timeout=8,
        )
        resp.raise_for_status()
        ctype = resp.headers.get("Content-Type", "").lower()
        if "html" not in ctype and "text" not in ctype:
            return ""  # PDF/ảnh... — không bóc text được
        soup = BeautifulSoup(resp.text, "lxml")
        # Bỏ các khối không phải nội dung để giảm nhiễu (menu, chân trang, script...).
        for tag in soup(
            ["script", "style", "noscript", "header", "footer", "nav", "form", "svg"]
        ):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)  # gộp khoảng trắng/xuống dòng thừa
        return text[:max_chars]
    except Exception as e:  # mạng lỗi / chặn bot / parse lỗi -> bỏ qua, dùng snippet
        logger.warning(f"Fetch page failed {url}: {e}")
        return ""


class BraveSearchArgs(BaseModel):
    query: str = Field(..., description="truy vấn tìm kiếm web bằng tiếng Việt")


class BraveSearchTool(CitableTool):
    """Tìm kiếm web qua Brave Search API (nguồn tham khảo bổ sung ngoài corpus)."""

    name: str = "web_search"
    # Mô tả mang luôn "khi nào dùng" (mục C) — KHÔNG nhắc tên tool khác, chỉ nói
    # vai trò bổ sung khi nguồn nội bộ thiếu; thứ tự ưu tiên do `priority` lo.
    description: str = (
        "Tìm kiếm trên internet (Brave Search) để BỔ SUNG khi nguồn dữ liệu nội bộ "
        "chính thống KHÔNG có hoặc còn thiếu (vd thông tin mới, chi tiết liên hệ cụ thể "
        "của một cơ quan tại địa bàn mà nguồn nội bộ chỉ nói chung chung). Đầu vào là "
        "truy vấn tìm kiếm tiếng Việt. Kết quả là thông tin tham khảo từ web, CHƯA thẩm định."
    )
    args_schema: Optional[Type[BaseModel]] = BraveSearchArgs

    # Nguồn tham khảo → liệt kê/dùng SAU nguồn chính thống (mục C).
    priority: int = 50

    # Số kết quả lấy về. Đọc key từ .env mỗi lần gọi (để đổi key không cần restart).
    count: int = 5

    # Số kết quả ĐẦU sẽ fetch nội dung trang đầy đủ (để lấy địa chỉ/giờ/SĐT mà snippet
    # thiếu). Giữ nhỏ vì mỗi fetch tốn thêm ~1 request đồng bộ; các kết quả sau chỉ dùng
    # snippet. fetch_max_chars: cắt nội dung mỗi trang tránh phình ngữ cảnh pha synthesis.
    fetch_count: int = 2
    fetch_max_chars: int = 2000

    # doc_sink + emit() thừa kế từ CitableTool: mỗi kết quả web được bọc thành một
    # Document citable rồi emit() để pha synthesis tạo inline citation. Pipeline gán
    # doc_sink qua bind() mỗi câu hỏi (xem reasoning/react.py:get_pipeline).

    def _run_tool(self, query: AnyStr) -> Document:
        api_key = config("BRAVE_API_KEY", default="")
        if not api_key:
            return Document(
                content=(
                    "Chưa cấu hình BRAVE_API_KEY nên không thể tìm web. "
                    "Hãy trả lời dựa trên thông tin đã có hoặc báo người dùng."
                )
            )

        try:
            resp = requests.get(
                BRAVE_ENDPOINT,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                },
                # Brave KHÔNG hỗ trợ country='VN' (sẽ 422). Để mặc định; truy vấn
                # tiếng Việt tự khắc cho kết quả tiếng Việt là chính.
                params={
                    "q": str(query),
                    "count": self.count,
                },
                timeout=15,
            )
            resp.raise_for_status()
            results = (resp.json().get("web", {}) or {}).get("results", []) or []
        except Exception as e:  # mạng lỗi / quota / key sai -> báo nhẹ, không crash agent
            logger.warning(f"Brave search failed: {e}")
            return Document(
                content=f"Tìm kiếm web thất bại ({e}). Hãy trả lời dựa trên thông tin đã có."
            )

        if not results:
            return Document(content="Không tìm thấy kết quả web nào cho truy vấn này.")

        # Fetch SONG SONG nội dung fetch_count trang đầu (chỉ khi cần gom nguồn cho pha 2).
        # Snippet của Brave thường thiếu địa chỉ/giờ/SĐT — fetch để synthesis có dữ liệu
        # thật. Chạy song song để tổng thời gian ≈ trang chậm nhất thay vì cộng dồn.
        # Key theo i (1-based) khớp vòng lặp dưới; trang lỗi/rỗng không có mặt trong dict.
        page_texts: dict = {}
        if self.doc_sink is not None and self.fetch_count > 0:
            to_fetch = [
                (i, item.get("url", ""))
                for i, item in enumerate(results[: self.fetch_count], 1)
                if item.get("url")
            ]
            if to_fetch:
                with ThreadPoolExecutor(max_workers=len(to_fetch)) as ex:
                    fetched = ex.map(
                        lambda u: _fetch_page_text(u, self.fetch_max_chars),
                        [u for _, u in to_fetch],
                    )
                    for (i, _), text in zip(to_fetch, fetched):
                        if text:
                            page_texts[i] = text

        # Observation cho agent (vòng lặp ReAct) — gọn, chỉ để agent biết web có kết quả.
        lines = []
        for i, item in enumerate(results, 1):
            title = _strip_html(item.get("title", ""))
            desc = _strip_html(item.get("description", ""))
            url = item.get("url", "")
            lines.append(f"{i}. {title}\n{desc}\nNguồn: {url}")

            # Bọc mỗi kết quả thành một nguồn citable cho pha synthesis.
            if self.doc_sink is not None:
                domain = urlparse(url).netloc or "web"
                # text phải chứa nguyên văn cụm mà LLM sẽ COPY làm START/END_PHRASE.
                # Với fetch_count kết quả ĐẦU: dùng nội dung trang (fetch song song ở trên)
                # để có chi tiết cụ thể; kết quả sau (hoặc fetch lỗi) chỉ dùng snippet.
                doc_text = f"{title}. {desc}".strip()
                page_text = page_texts.get(i)
                if page_text:
                    doc_text = f"{title}. {desc}\n{page_text}".strip()
                # RetrievedDocument (không phải Document) vì Render.collapsible_with_header_score
                # đọc doc.score — Document thường không có field này (gây AttributeError).
                self.emit(
                    RetrievedDocument(
                        text=doc_text,
                        score=WEB_DOC_SCORE,
                        metadata={
                            "file_name": f"{WEB_SOURCE_MARK} {domain} · web",
                            "type": "text",
                            "llm_trulens_score": WEB_DOC_SCORE,
                            "web_url": url,
                            "is_web": True,
                        },
                    )
                )

        return Document(content="\n\n".join(lines))
