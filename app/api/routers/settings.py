"""Settings: schema option (render form) + setting hiện tại (defaults + override) + lưu."""
from fastapi import APIRouter
from pydantic import BaseModel

from .. import store
from ..context import default_settings_dict, get_context

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPut(BaseModel):
    setting: dict  # phần override (key phẳng, vd "reasoning.use")


@router.get("/schema")
def schema():
    """Các engine khả dụng + user-settings từng engine (choices llm/tool...)."""
    from ktem.components import reasonings

    engines = []
    for rid, cls in reasonings.items():
        info = cls.get_info()
        engines.append({
            "id": rid,
            "name": info.get("name", rid),
            "description": info.get("description", ""),
            "options": cls.get_user_settings(),
        })
    app_settings = get_context().default_settings.flatten()
    return {
        "engines": engines,
        "default_reasoning": app_settings.get("reasoning.use"),
        "default_lang": app_settings.get("reasoning.lang"),
    }


@router.get("")
def current():
    """Defaults phủ bởi override đã lưu của user."""
    merged = default_settings_dict()
    merged.update(store.get_user_setting())
    return {"settings": merged}


@router.put("")
def update(req: SettingsPut):
    store.save_user_setting(req.setting)
    merged = default_settings_dict()
    merged.update(req.setting)
    return {"settings": merged}
