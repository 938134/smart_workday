"""Config flow for Smart Workday.

v2.8.0 重度简化：
- ConfigFlow：1 步（名称 + 3 开关 + 可选一键导入法定假期）
- OptionsFlow：1 步（3 开关 + 可选一键导入）→ 完成后 HA 自动 reload
- 所有分类编辑（法定/学生/自定义的增删）统一走日历 UI（CREATE/DELETE_EVENT）
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, override

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    DEFAULT_NAME,
    DEFAULT_LEGAL_YEAR,
    LEGAL_HOLIDAY_PRESETS,
    STORAGE_VERSION,
    CONF_ENABLED_LEGAL,
    CONF_ENABLED_STUDENT,
    CONF_ENABLED_CUSTOM,
    CONF_NAME,
    CONF_IMPORT_LEGAL,
    CONF_IMPORT_LEGAL_YEAR,
)

_LOGGER = logging.getLogger(__name__)


def _build_year_options() -> List[selector.SelectOptionDict]:
    """可用导入年份（从预置数据推导，无需硬编码）"""
    return [
        selector.SelectOptionDict(
            value=str(year), label=f"{year} 年国务院通知"
        )
        for year in sorted(LEGAL_HOLIDAY_PRESETS.keys())
    ]


# ============================================================
# ConfigFlow - 首次添加集成（1 步）
# ============================================================

class SmartWorkdayConfigFlow(ConfigFlow, domain=DOMAIN):
    """首次添加：名称 + 3 个启用开关 + 可选一键导入法定假期。

    创建条目后 HA 会自动跳到 OptionsFlow 继续（用户可再次确认开关或直接完成）。
    """

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry):
        """获取选项流"""
        return SmartWorkdayOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """第 1 步（也是唯一一步）：名称 + 3 个启用开关 + 可选一键导入法定假期"""
        if user_input is not None:
            name = (user_input.get(CONF_NAME) or DEFAULT_NAME).strip() or DEFAULT_NAME
            data = {
                CONF_NAME: name,
                CONF_ENABLED_LEGAL: bool(user_input[CONF_ENABLED_LEGAL]),
                CONF_ENABLED_STUDENT: bool(user_input[CONF_ENABLED_STUDENT]),
                CONF_ENABLED_CUSTOM: bool(user_input[CONF_ENABLED_CUSTOM]),
                CONF_IMPORT_LEGAL: bool(user_input.get(CONF_IMPORT_LEGAL, False)),
                CONF_IMPORT_LEGAL_YEAR: int(
                    user_input.get(CONF_IMPORT_LEGAL_YEAR, DEFAULT_LEGAL_YEAR)
                ),
            }
            return self.async_create_entry(title=name, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
                vol.Required(CONF_ENABLED_LEGAL, default=True): selector.BooleanSelector(),
                vol.Required(CONF_ENABLED_STUDENT, default=True): selector.BooleanSelector(),
                vol.Required(CONF_ENABLED_CUSTOM, default=True): selector.BooleanSelector(),
                vol.Required(CONF_IMPORT_LEGAL, default=False): selector.BooleanSelector(),
                vol.Required(
                    CONF_IMPORT_LEGAL_YEAR, default=str(DEFAULT_LEGAL_YEAR)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_build_year_options(), mode="dropdown")
                ),
            }),
            description_placeholders={
                "tips": (
                    f"⚙️ 输入集成名称、勾选要启用的假期类型。\n"
                    f"📥 勾选「立即导入」可一键填充 {DEFAULT_LEGAL_YEAR} 年国务院法定假期数据。\n"
                    f"💡 提交后会跳到下一步继续详细配置。"
                ),
            },
        )


# ============================================================
# OptionsFlow - 修改配置（1 步：开关 + 可选导入）
# ============================================================

class SmartWorkdayOptionsFlow(OptionsFlowWithReload):
    """选项流：3 个启用开关 + 可选一键导入法定假期。

    继承 OptionsFlowWithReload：async_create_entry 自动 reload entry。
    ⚠️ 不要覆盖 __init__：HA 会自动注入 self.config_entry。
    """

    @override
    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """1 步：保存开关 + 可选导入 → 完成（HA 自动 reload）"""
        if user_input is not None:
            flags = {
                CONF_ENABLED_LEGAL: bool(user_input[CONF_ENABLED_LEGAL]),
                CONF_ENABLED_STUDENT: bool(user_input[CONF_ENABLED_STUDENT]),
                CONF_ENABLED_CUSTOM: bool(user_input[CONF_ENABLED_CUSTOM]),
            }
            new_data = dict(self.config_entry.data)
            new_data.update(flags)

            # 处理可选导入（覆盖当前法定假期）
            if bool(user_input.get(CONF_IMPORT_LEGAL, False)):
                import_year = int(
                    user_input.get(CONF_IMPORT_LEGAL_YEAR, DEFAULT_LEGAL_YEAR)
                )
                presets = LEGAL_HOLIDAY_PRESETS.get(import_year, [])
                if presets:
                    data = await self._load_data()
                    data["holidays"] = [
                        {
                            "name": item["name"],
                            "date": item["date"],
                            "uid": str(uuid.uuid4())[:8],
                        }
                        for item in presets
                    ]
                    await self._save_data(data)
                    _LOGGER.info(
                        "已导入 %d 条法定假期（%d 年）", len(presets), import_year
                    )

            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            return self.async_create_entry(title="", data={})

        current = self._get_flags()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_ENABLED_LEGAL, default=current[CONF_ENABLED_LEGAL]
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_ENABLED_STUDENT, default=current[CONF_ENABLED_STUDENT]
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_ENABLED_CUSTOM, default=current[CONF_ENABLED_CUSTOM]
                ): selector.BooleanSelector(),
                vol.Required(CONF_IMPORT_LEGAL, default=False): selector.BooleanSelector(),
                vol.Required(
                    CONF_IMPORT_LEGAL_YEAR, default=str(DEFAULT_LEGAL_YEAR)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_build_year_options(), mode="dropdown")
                ),
            }),
            description_placeholders={
                "tips": self._build_init_tips(current),
            },
        )

    # ---------- 内部工具 ----------

    def _get_flags(self) -> Dict[str, bool]:
        """读取当前 entry.data 中的开关（向后兼容：缺字段默认 True）"""
        d = self.config_entry.data
        return {
            CONF_ENABLED_LEGAL: bool(d.get(CONF_ENABLED_LEGAL, True)),
            CONF_ENABLED_STUDENT: bool(d.get(CONF_ENABLED_STUDENT, True)),
            CONF_ENABLED_CUSTOM: bool(d.get(CONF_ENABLED_CUSTOM, True)),
        }

    def _get_store(self) -> Store:
        return Store(
            self.hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{self.config_entry.entry_id}",
        )

    async def _load_data(self) -> Dict[str, Any]:
        try:
            data = await self._get_store().async_load()
            if not isinstance(data, dict):
                data = {}
            data.setdefault("holidays", [])
            data.setdefault("customdays", [])
            data.setdefault("studentdays", [])
            return data
        except Exception as e:
            _LOGGER.error("加载数据失败: %s", e)
            return {"holidays": [], "customdays": [], "studentdays": []}

    async def _save_data(self, data: Dict[str, Any]) -> bool:
        try:
            for key in ("holidays", "customdays", "studentdays"):
                data[key] = data.get(key, [])
                data[key].sort(key=lambda x: x.get("date") or x.get("start", ""))
            await self._get_store().async_save(data)
            return True
        except Exception as e:
            _LOGGER.error("保存数据失败: %s", e)
            return False

    def _build_init_tips(self, flags: Dict[str, bool]) -> str:
        return (
            f"⚙️ **当前配置**\n"
            f"  • 📅 法定假期：{'✅ 启用' if flags[CONF_ENABLED_LEGAL] else '❌ 禁用'}\n"
            f"  • 🎓 学生假期：{'✅ 启用' if flags[CONF_ENABLED_STUDENT] else '❌ 禁用'}\n"
            f"  • ⭐ 自定义假期：{'✅ 启用' if flags[CONF_ENABLED_CUSTOM] else '❌ 禁用'}\n"
            f"\n📥 勾选「立即导入」可用国务院通知覆盖当前法定假期。\n"
            f"💡 假期条目的增删请通过日历实体完成（支持 CREATE/DELETE_EVENT）。"
        )
