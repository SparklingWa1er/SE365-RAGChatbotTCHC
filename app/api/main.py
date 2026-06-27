"""FastAPI entry cho UI React. Chạy TỪ GỐC REPO:

    .venv\\Scripts\\python.exe -m uvicorn app.api.main:app --reload --port 8000

Hoặc:  .venv\\Scripts\\python.exe app\\api\\main.py
"""
# context.py phải import TRƯỚC ktem để bootstrap sys.path + flowsettings file-based.
from .context import get_context  # noqa: F401  (đặt đầu để chạy bootstrap)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import (
    chat,
    conversations,
    indices,
    places,
    settings,
    suggestions,
    system,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # khởi tạo BaseApp (index_manager, reasonings, default_settings) MỘT LẦN
    get_context()
    yield


app = FastAPI(title="DVC RAG API", version="0.1.0", lifespan=lifespan)

# CORS cho frontend React dev (Vite mặc định 5173). Chỉnh theo môi trường.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Conversation-Id"],
)

for r in (system, chat, conversations, suggestions, settings, indices, places):
    app.include_router(r.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.api.main:app", host="127.0.0.1", port=8000, reload=False)
