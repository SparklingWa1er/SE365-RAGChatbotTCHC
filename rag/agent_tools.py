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
from typing import AnyStr, Optional, Type
from urllib.parse import urlparse

import requests
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

# Nhãn gọn cho nguồn web (dùng làm file_name của web-doc). Pha synthesis nhận diện
# tiền tố 🌐 này để gắn ký hiệu trích dẫn riêng (xem rag/prompts.py:REACT_QA_CITATION_PROMPT)
# và phân biệt với nguồn corpus chính thống trong panel Information.
WEB_SOURCE_MARK = "🌐"

# Điểm relevance gán cho web-doc: đặt < ngưỡng cảnh báo corpus (CONTEXT_RELEVANT_WARNING_SCORE
# mặc định 0.3) là cố ý — web chưa thẩm định nên không nên tỏ ra "rất liên quan"; nhưng > 0
# để không bị relevance-gate loại nhầm. Đủ để hiển thị + sắp xếp trong panel nguồn.
WEB_DOC_SCORE = 0.2

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def _strip_html(text: str) -> str:
    """Brave trả description có thể kèm thẻ <strong> highlight — bỏ thẻ + unescape."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


class BraveSearchArgs(BaseModel):
    query: str = Field(..., description="truy vấn tìm kiếm web bằng tiếng Việt")


class BraveSearchTool(BaseTool):
    """Tìm kiếm web qua Brave Search API (fallback ngoài corpus)."""

    name: str = "web_search"
    description: str = (
        "Tìm kiếm trên internet (Brave Search). CHỈ dùng khi công cụ docsearch đã báo "
        "không có tài liệu liên quan trong cơ sở dữ liệu nội bộ, hoặc câu hỏi về thông "
        "tin mới/ngoài phạm vi thủ tục đã lưu. Đầu vào là truy vấn tìm kiếm tiếng Việt. "
        "Kết quả là thông tin tham khảo từ web, CHƯA thẩm định."
    )
    args_schema: Optional[Type[BaseModel]] = BraveSearchArgs

    # Số kết quả lấy về. Đọc key từ .env mỗi lần gọi (để đổi key không cần restart).
    count: int = 5

    # Bể gom nguồn (do pipeline gán mỗi request): mỗi kết quả web được bọc thành một
    # Document citable rồi append vào đây để pha synthesis tạo inline citation. Pipeline
    # reset list này mỗi câu hỏi (xem reasoning/react.py:get_pipeline). Để None = không gom.
    doc_sink: Optional[list] = None

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
                doc_text = f"{title}. {desc}".strip()
                # RetrievedDocument (không phải Document) vì Render.collapsible_with_header_score
                # đọc doc.score — Document thường không có field này (gây AttributeError).
                self.doc_sink.append(
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
