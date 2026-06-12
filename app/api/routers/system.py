"""Health + config feature flags."""
from fastapi import APIRouter

from ..context import get_context

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    ctx = get_context()
    n_indices = len(ctx.index_manager.indices)
    return {"status": "ok", "indices": n_indices}


@router.get("/config")
def config():
    from theflow.settings import settings as flowsettings

    return {
        "chat_suggestion": getattr(flowsettings, "KH_FEATURE_CHAT_SUGGESTION", False),
        "default_lang": get_context().default_settings.flatten().get("reasoning.lang"),
        "app_name": getattr(flowsettings, "KH_APP_NAME", "Kotaemon"),
    }
