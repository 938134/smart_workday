"""Config flow for Smart Workday.

v2.9.0 极简版：
- ConfigFlow：1 步（名称 + 3 开关）
- OptionsFlow：1 步（3 开关）
- 法定假期启用时自动从国务院通知导入（无需手动勾选）
- 所有分类编辑（法定/学生/自定义的增删）统一走日历 UI（CREATE/DELETE_EVENT）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, override

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

from .const import (
    DOMAIN,
    DEFAULT_NAME,
    CONF_ENABLED_LEGAL,
    CONF_ENABLED_STUDENT,
    CONF_ENABLED_CUSTOM,
    CONF_NAME,
)

_LOGGER = logging.getLogger(__name__)


# ============================================================
# ConfigFlow - 首次添加集成（1 步）
# ============================================================

class SmartWorkdayConfigFlow(ConfigFlow, domain=DOMAIN):
    """首次添加：名称 + 3 个启用开关。

    创建条目后 HA 会自动跳到 OptionsFlow 继续。
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
        """唯一一步：名称 + 3 个启用开关"""
        if user_input is not None:
            name = (user_input.get(CONF_NAME) or DEFAULT_NAME).strip() or DEFAULT_NAME
            data = {
                CONF_NAME: name,
                CONF_ENABLED_LEGAL: bool(user_input[CONF_ENABLED_LEGAL]),
                CONF_ENABLED_STUDENT: bool(user_input[CONF_ENABLED_STUDENT]),
                CONF_ENABLED_CUSTOM: bool(user_input[CONF_ENABLED_CUSTOM]),
            }
            return self.async_create_entry(title=name, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
                vol.Required(CONF_ENABLED_LEGAL, default=True): selector.BooleanSelector(),
                vol.Required(CONF_ENABLED_STUDENT, default=True): selector.BooleanSelector(),
                vol.Required(CONF_ENABLED_CUSTOM, default=True): selector.BooleanSelector(),
            }),
            description_placeholders={
                "tips": (
                    "⚙️ 输入集成名称、勾选要启用的假期类型。\n"
                    "📅 启用法定假期将自动导入当年国务院通知数据。\n"
                    "💡 假期条目通过日历实体添加（3 个日历：法定/学生/自定义），\n"
                    "   在哪个日历上添加就归入哪个分类。"
                ),
            },
        )


# ============================================================
# OptionsFlow - 修改配置（1 步：3 开关）
# ============================================================

class SmartWorkdayOptionsFlow(OptionsFlowWithReload):
    """选项流：3 个启用开关。

    继承 OptionsFlowWithReload：async_create_entry 自动 reload entry。
    ⚠️ 不要覆盖 __init__：HA 会自动注入 self.config_entry。
    """

    @override
    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """1 步：保存开关 → 完成（HA 自动 reload）"""
        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data[CONF_ENABLED_LEGAL] = bool(user_input[CONF_ENABLED_LEGAL])
            new_data[CONF_ENABLED_STUDENT] = bool(user_input[CONF_ENABLED_STUDENT])
            new_data[CONF_ENABLED_CUSTOM] = bool(user_input[CONF_ENABLED_CUSTOM])
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        current = self._get_flags()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_ENABLED_LEGAL, default=current[CONF_ENABLED_LEGAL]):
                    selector.BooleanSelector(),
                vol.Required(CONF_ENABLED_STUDENT, default=current[CONF_ENABLED_STUDENT]):
                    selector.BooleanSelector(),
                vol.Required(CONF_ENABLED_CUSTOM, default=current[CONF_ENABLED_CUSTOM]):
                    selector.BooleanSelector(),
            }),
            description_placeholders={
                "tips": self._build_init_tips(current),
            },
        )

    def _get_flags(self) -> Dict[str, bool]:
        """读取当前 entry.data 中的开关（向后兼容：缺字段默认 True）"""
        d = self.config_entry.data
        return {
            CONF_ENABLED_LEGAL: bool(d.get(CONF_ENABLED_LEGAL, True)),
            CONF_ENABLED_STUDENT: bool(d.get(CONF_ENABLED_STUDENT, True)),
            CONF_ENABLED_CUSTOM: bool(d.get(CONF_ENABLED_CUSTOM, True)),
        }

    def _build_init_tips(self, flags: Dict[str, bool]) -> str:
        return (
            "⚙️ **当前配置**\n"
            f"  • 📅 法定假期：{'✅ 启用' if flags[CONF_ENABLED_LEGAL] else '❌ 禁用'}\n"
            f"  • 🎓 学生假期：{'✅ 启用' if flags[CONF_ENABLED_STUDENT] else '❌ 禁用'}\n"
            f"  • ⭐ 自定义假期：{'✅ 启用' if flags[CONF_ENABLED_CUSTOM] else '❌ 禁用'}\n"
            "\n💡 **添加事件**：在 HA 日历 UI 的下拉菜单里选对应日历添加：\n"
            "  • 法定假期日历 → 法定假期 / 调休上班日\n"
            "  • 学生假期日历 → 学生假期\n"
            "  • 自定义假期日历 → 自定义假期\n"
            "\n📅 启用法定假期时会自动从国务院通知导入当年数据（仅当节假日列表为空时）。"
        )
