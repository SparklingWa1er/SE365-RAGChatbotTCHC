"""Sinh constraints.txt từ uv.lock của kotaemon.

Pin các họ package mà CODE kotaemon nhạy version (langchain*, llama-index*,
huggingface-hub, pydantic, gradio...) về đúng bản đã test trong uv.lock — tránh
việc uv chọn bản mới nhất gây lỗi import (langchain.schema, HfFolder...).

Chạy TỪ thư mục chứa uv.lock của kotaemon:
    python <repo>/scripts/gen_constraints.py
-> tạo ./constraints.txt (rồi chép về gốc repo)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Chỉ pin các họ package gây xung đột version với code kotaemon.
KEEP_PREFIX = (
    "langchain", "llama-index", "llama-hub", "huggingface-hub",
    "pydantic", "openai", "tiktoken", "tokenizers", "transformers",
    "chromadb", "theflow", "gradio",
)


def main() -> int:
    lock = Path("uv.lock")
    if not lock.exists():
        print("Không thấy uv.lock — hãy chạy script này từ thư mục có uv.lock.")
        return 1

    txt = lock.read_text(encoding="utf-8")
    pkgs = re.findall(
        r'\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"', txt
    )
    seen: dict[str, str] = {}
    for name, version in pkgs:
        if any(name == p or name.startswith(p) for p in KEEP_PREFIX) and name not in seen:
            seen[name] = version

    out = Path("constraints.txt")
    out.write_text("".join(f"{n}=={v}\n" for n, v in seen.items()), encoding="utf-8")
    print(f"Đã ghi {len(seen)} pin vào {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
