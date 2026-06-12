"""Bootstrap + singleton context cho tầng API.

`BaseApp.__init__` (ktem/app.py) KHÔNG dựng UI Gradio — chỉ đăng ký index_manager,
default_settings, reasonings. Ta khởi tạo nó MỘT LẦN lúc startup để tái dùng cho mọi
request, đúng như ChatPage làm qua self._app.

Phải chèn sys.path y như app/app.py TRƯỚC khi import ktem để theflow nạp được
rag/flowsettings.py kiểu file-based (KHÔNG set THEFLOW_SETTINGS_MODULE).
"""
import os
import sys
from pathlib import Path

# --- bootstrap sys.path (giống app/app.py) ---
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # .../<repo>
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "rag")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from theflow.settings import settings as flowsettings  # noqa: E402

# GRADIO_TEMP_DIR vẫn cần vì vài module ktem đọc nó lúc import
_DATA_DIR = getattr(flowsettings, "KH_APP_DATA_DIR", ".")
os.environ.setdefault("GRADIO_TEMP_DIR", os.path.join(_DATA_DIR, "gradio_tmp"))

from ktem.app import BaseApp  # noqa: E402

# user mặc định khi tắt user-management (KH_FEATURE_USER_MANAGEMENT=false).
# Khớp với BaseApp.user_id = gr.State("default"). Với index private=false, giá trị này
# không ảnh hưởng lọc file (xem LỖI #4 trong CLAUDE.md).
DEFAULT_USER_ID = "default"


class _HeadlessApp(BaseApp):
    """BaseApp nhưng KHÔNG dựng UI. ui() không bao giờ được gọi vì ta không make()."""

    def ui(self):  # pragma: no cover - không dùng
        raise NotImplementedError("Headless app: UI bị tắt")


_app_ctx: "_HeadlessApp | None" = None


def get_context() -> "_HeadlessApp":
    """Trả về singleton BaseApp (lazy init). Gọi lúc FastAPI startup."""
    global _app_ctx
    if _app_ctx is None:
        _app_ctx = _HeadlessApp()
    return _app_ctx


def default_settings_dict() -> dict:
    """Dict setting phẳng (giống self._app.settings_state.value trong Gradio)."""
    return get_context().default_settings.flatten()
