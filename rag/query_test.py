"""Test RAG end-to-end: truy hồi (Azure text-embedding-3-large) + sinh câu trả lời (Azure gpt-4o).

Bootstrap app -> lấy retriever của FileIndex -> truy hồi đoạn liên quan ->
nhồi vào prompt tiếng Việt -> Azure LLM trả lời + trích nguồn.

Chạy (từ gốc repo):
  .venv\\Scripts\\python.exe rag\\query_test.py
  .venv\\Scripts\\python.exe rag\\query_test.py "câu hỏi của bạn"
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# Bootstrap: chèn gốc repo + thư mục rag/ vào sys.path để (1) import được package
# `rag` (rag.prompts mà lib đã vá dùng) và (2) theflow tự tìm thấy flowsettings.py.
# KHÔNG set THEFLOW_SETTINGS_MODULE — tránh vòng lặp import (xem ingest_corpus.py).
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # gốc repo -> package `rag`
sys.path.insert(0, str(_HERE))         # rag/ -> theflow tìm flowsettings.py

import flowsettings  # noqa: E402
from ktem.main import App  # noqa: E402
from kotaemon.llms import AzureChatOpenAI  # noqa: E402

SYSTEM = (
    "Bạn là trợ lý hướng dẫn thủ tục hành chính công Việt Nam. "
    "Chỉ trả lời dựa trên NGỮ CẢNH được cung cấp, bằng tiếng Việt, rõ ràng, "
    "đúng trọng tâm. Khi có thể, nêu mã thủ tục và trích dẫn căn cứ pháp lý. "
    "Nếu ngữ cảnh không đủ thông tin, hãy nói rõ là không tìm thấy."
)

DEFAULT_QUESTIONS = [
    "Hồ sơ xin phép trường mầm non hoạt động giáo dục gồm những giấy tờ gì?",
    "Thời hạn giải quyết thủ tục cho phép trường mầm non hoạt động là bao lâu?",
]


def all_doc_ids(file_index):
    """Lấy id của mọi tài liệu đã ingest (retriever bắt buộc có doc_ids)."""
    from ktem.db.engine import engine
    from sqlmodel import Session, select

    Source = file_index._resources["Source"]
    with Session(engine) as s:
        return [r[0].id for r in s.execute(select(Source)).all()]


def build_retrievers(file_index, settings):
    """Dựng retriever trực tiếp (bỏ qua _selector_ui vốn chỉ có khi chạy UI)."""
    prefix = f"index.options.{file_index.id}."
    stripped = {k[len(prefix):]: v for k, v in settings.items() if k.startswith(prefix)}
    selected = all_doc_ids(file_index)  # truy hồi trên toàn bộ tài liệu
    print(f"  (tổng tài liệu trong index: {len(selected)})")
    retrievers = []
    for cls in file_index._retriever_pipeline_cls:
        obj = cls.get_pipeline(stripped, file_index.config, selected)
        if obj is None:
            continue
        obj.Source = file_index._resources["Source"]
        obj.Index = file_index._resources["Index"]
        obj.VS = file_index._vs
        obj.DS = file_index._docstore
        obj.FSPath = file_index._fs_path
        obj.user_id = "default"
        retrievers.append(obj)
    return retrievers


def main() -> int:
    questions = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else DEFAULT_QUESTIONS

    print("Khởi tạo kotaemon...")
    app = App()
    settings = app.default_settings.flatten()
    file_index = next(
        i for i in app.index_manager.indices if type(i).__name__ == "FileIndex"
    )
    retrievers = build_retrievers(file_index, settings)

    spec = flowsettings.KH_LLMS["azure"]["spec"].copy()
    spec.pop("__type__")
    llm = AzureChatOpenAI(**spec)

    for q in questions:
        print("\n" + "=" * 70)
        print("CÂU HỎI:", q)
        docs = []
        for r in retrievers:
            try:
                docs += r(q)
            except Exception as e:  # noqa: BLE001
                print("  (retriever lỗi:", e, ")")
        if not docs:
            print("  -> Không truy hồi được đoạn nào (đã ingest chưa?).")
            continue

        print(f"  Truy hồi {len(docs)} đoạn. Nguồn:")
        for d in docs[:5]:
            meta = getattr(d, "metadata", {}) or {}
            print(f"    - {meta.get('ma_thu_tuc', '?')} | {meta.get('file_name', meta.get('ten',''))[:60]}")

        context = "\n\n---\n\n".join(d.text for d in docs[:6])
        prompt = (
            f"{SYSTEM}\n\nNGỮ CẢNH:\n{context}\n\n"
            f"CÂU HỎI: {q}\n\nTRẢ LỜI:"
        )
        ans = llm(prompt)
        print("\nTRẢ LỜI:")
        print(ans.text if hasattr(ans, "text") else str(ans))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
