"""Nạp corpus Markdown thủ tục hành chính vào kotaemon (FileIndex).

Bootstrap app headless -> lấy indexing pipeline -> stream các file .md vào
vector store (embedding bge-m3) + doc store.

Lần chạy ĐẦU sẽ tải model bge-m3 (~2GB qua fastembed) nên hơi lâu.

Chạy:
  .venv/Scripts/python.exe ingest_corpus.py                 # nạp toàn bộ corpus
  .venv/Scripts/python.exe ingest_corpus.py --limit 5       # thử 5 file
  .venv/Scripts/python.exe ingest_corpus.py --reindex       # nạp lại (ghi đè)
  .venv/Scripts/python.exe ingest_corpus.py --corpus <dir>  # đổi thư mục .md
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# Bootstrap: chèn gốc repo + thư mục rag/ vào sys.path để (1) import được package
# `rag` (rag.prompts mà lib đã vá dùng) và (2) theflow tự tìm thấy flowsettings.py.
# KHÔNG set THEFLOW_SETTINGS_MODULE — để theflow nạp flowsettings kiểu file-based,
# tránh vòng lặp import (flowsettings.py có import ngược theflow/ktem).
import sys  # noqa: E402

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # gốc repo -> package `rag`
sys.path.insert(0, str(_HERE))         # rag/ -> theflow tìm flowsettings.py

import flowsettings  # noqa: F401,E402  -> đọc .env, tạo thư mục app data
from ktem.main import App  # noqa: E402

DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "data" / "corpus" / "md"


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest corpus Markdown vào kotaemon")
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="Thư mục chứa *.md")
    ap.add_argument("--limit", type=int, default=None, help="Giới hạn số file (thử)")
    ap.add_argument("--reindex", action="store_true", help="Nạp lại file đã có")
    args = ap.parse_args()

    files = sorted(str(p) for p in Path(args.corpus).glob("*.md"))
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"Không tìm thấy .md trong {args.corpus}")
        return 1
    print(f"Chuẩn bị nạp {len(files)} file từ {args.corpus}")

    print("Khởi tạo kotaemon (lần đầu sẽ tải model bge-m3 ~2GB)...")
    app = App()
    settings = app.default_settings.flatten()
    user_id = "default"  # user-management đã tắt trong .env
    file_index = next(
        i for i in app.index_manager.indices if type(i).__name__ == "FileIndex"
    )
    pipeline = file_index.get_indexing_pipeline(settings, user_id)

    print("Bắt đầu indexing...")
    ok = fail = 0
    stream = pipeline.stream(files, reindex=args.reindex)
    try:
        while True:
            response = next(stream)
            if response is None:
                continue
            if response.channel == "index":
                content = response.content
                if content["status"] == "success":
                    ok += 1
                    print(f"  ✅ {ok}/{len(files)} | {Path(content['file_name']).name}")
                elif content["status"] == "failed":
                    fail += 1
                    print(f"  ❌ {content['file_name']}: {content.get('message')}")
    except StopIteration as e:
        results = e.value[0] if isinstance(e.value, tuple) else e.value

    print(f"\nXONG: thành công ~{ok}, lỗi {fail}.")
    print("Khởi động chatbot bằng: .venv/Scripts/python.exe app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
