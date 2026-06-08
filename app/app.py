import os
import sys
from pathlib import Path

# Bootstrap: chèn gốc repo + thư mục rag/ vào sys.path để (1) import được package
# `rag` (rag.prompts mà lib đã vá dùng) và (2) theflow tự tìm thấy flowsettings.py
# kiểu file-based. KHÔNG set THEFLOW_SETTINGS_MODULE để tránh vòng lặp import.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))           # gốc repo -> package `rag`
sys.path.insert(0, str(_REPO_ROOT / "rag"))   # rag/ -> theflow tìm flowsettings.py

from theflow.settings import settings as flowsettings  # noqa: E402

KH_APP_DATA_DIR = getattr(flowsettings, "KH_APP_DATA_DIR", ".")
KH_GRADIO_SHARE = getattr(flowsettings, "KH_GRADIO_SHARE", False)
GRADIO_TEMP_DIR = os.getenv("GRADIO_TEMP_DIR", None)
# override GRADIO_TEMP_DIR if it's not set
if GRADIO_TEMP_DIR is None:
    GRADIO_TEMP_DIR = os.path.join(KH_APP_DATA_DIR, "gradio_tmp")
    os.environ["GRADIO_TEMP_DIR"] = GRADIO_TEMP_DIR


from ktem.main import App  # noqa

app = App()
demo = app.make()
demo.queue().launch(
    favicon_path=app._favicon,
    inbrowser=True,
    allowed_paths=[
        str(_REPO_ROOT / "app" / "libs" / "ktem" / "ktem" / "assets"),
        GRADIO_TEMP_DIR,
    ],
    share=KH_GRADIO_SHARE,
)
