"""Config flow for Smart Workday.

v2.10.0 单日历 + OptionsFlow 表单录入：
- ConfigFlow：1 步（名称 + 3 开关）
- OptionsFlow：init（3 开关）→ menu（添加学生/自定义/完成）→ add_student/add_custom
- 法定假期自动从国务院通知导入，不支持手动添加
- 学生假期儿童节自动 6 月 1 日，无需输入日期
- 日历实体仅支持 DELETE_EVENT（录入走 OptionsFlow 表单）
"""

from __future__ import annotations

import logging
from datetime import date
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
    CONF_STUDENT_TYPE,
    CONF_START_DATE,
    CONF_END_DATE,
    CONF_CUSTOM_NAME,
    CONF_CUSTOM_DATE,
    STUDENT_HOLIDAY_TYPES,
    CHILDREN_DAY_MONTH,
    CHILDREN_DAY_DAY,
)

_LOGGER = logging.getLogger(__name__)


# ============================================================
# ConfigFlow - 首次添加集成（1 步）
# ============================================================

class SmartWorkdayConfigFlow(ConfigFlow, domain=DOMAIN):
    """首次添加：名称 + 3 个启用开关。"""

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
                    "💡 学生假期 / 自定义假期通过 Options Flow 表单添加。\n"
                    "   删除事件请在日历实体上操作。"
                ),
            },
        )


# ============================================================
# OptionsFlow - 修改配置 + 表单录入
# ============================================================

class SmartWorkdayOptionsFlow(OptionsFlowWithReload):
    """选项流：3 开关 + 添加学生/自定义假期表单。

    步骤：
    1. init   - 3 个启用开关
    2. menu   - 快捷菜单（添加学生 / 添加自定义 / 完成）
    3. add_student / add_custom - 表单录入
    4. finish - 保存并重载

    ⚠️ 不要覆盖 __init__：HA 会自动注入 self.config_entry。
    """

    @override
    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """第 1 步：保存 3 个启用开关 → 跳转菜单"""
        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data[CONF_ENABLED_LEGAL] = bool(user_input[CONF_ENABLED_LEGAL])
            new_data[CONF_ENABLED_STUDENT] = bool(user_input[CONF_ENABLED_STUDENT])
            new_data[CONF_ENABLED_CUSTOM] = bool(user_input[CONF_ENABLED_CUSTOM])
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return await self.async_step_menu()

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

    @override
    async def async_step_menu(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        """第 2 步：快捷菜单"""
        return self.async_show_menu(
            step_id="menu",
            menu_options=["add_student", "add_custom", "finish"],
            description_placeholders={
                "tips": (
                    "📅 法定假期自动从国务院通知导入，无需手动添加。\n"
                    "💡 删除事件请在日历实体上操作。"
                ),
            },
        )

    @override
    async def async_step_add_student(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """第 3 步：添加学生假期

        - 选"儿童节"时自动用当前年份 6 月 1 日覆盖，忽略用户输入
        - 其他类型使用用户输入的 start/end 日期
        """
        if user_input is not None:
            label = user_input[CONF_STUDENT_TYPE]  # 如 "🏔 寒假"
            type_cfg = self._get_student_type(label)
            if type_cfg is None:
                return await self.async_step_menu()

            current_year = date.today().year
            name_base = type_cfg["label"].split(" ", 1)[-1]  # 去掉 emoji 前缀
            name = f"{current_year} {name_base}"

            dm = self.hass.data[DOMAIN][self.config_entry.entry_id]["data_manager"]

            if type_cfg["single_day"]:
                # 儿童节：自动 6 月 1 日
                date_str = f"{current_year}-{CHILDREN_DAY_MONTH:02d}-{CHILDREN_DAY_DAY:02d}"
                ok = await dm.add_entry("studentdays", name, date_str, date_str)
            else:
                # 范围型：使用用户输入的 start/end
                start = user_input.get(CONF_START_DATE)
                end = user_input.get(CONF_END_DATE)
                if not start or not end:
                    return self.async_show_form(
                        step_id="add_student",
                        errors={"base": "请填写开始和结束日期"},
                    )
                ok = await dm.add_entry("studentdays", name, start, end)

            if not ok:
                return self.async_show_form(
                    step_id="add_student",
                    errors={"base": "保存失败，请检查日志"},
                )

            _LOGGER.info("已添加学生假期: %s", name)
            return await self.async_step_menu()

        return self.async_show_form(
            step_id="add_student",
            data_schema=vol.Schema({
                vol.Required(CONF_STUDENT_TYPE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[t["label"] for t in STUDENT_HOLIDAY_TYPES],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="student_type",
                    )
                ),
                vol.Required(CONF_START_DATE): selector.DateSelector(),
                vol.Required(CONF_END_DATE): selector.DateSelector(),
            }),
            description_placeholders={
                "tips": (
                    "🎓 **添加学生假期**\n"
                    "  • 选「🎉 儿童节」时自动设为当年 6 月 1 日（忽略日期输入）\n"
                    "  • 其他类型请填写开始/结束日期范围"
                ),
            },
        )

    @override
    async def async_step_add_custom(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """第 3 步：添加自定义假期（名称 + 单日日期）"""
        if user_input is not None:
            name = (user_input.get(CONF_CUSTOM_NAME) or "").strip()
            date_str = user_input.get(CONF_CUSTOM_DATE)
            if not name:
                return self.async_show_form(
                    step_id="add_custom",
                    errors={"base": "请填写假期名称"},
                )
            if not date_str:
                return self.async_show_form(
                    step_id="add_custom",
                    errors={"base": "请选择日期"},
                )

            dm = self.hass.data[DOMAIN][self.config_entry.entry_id]["data_manager"]
            ok = await dm.add_entry("customdays", name, date_str, None)
            if not ok:
                return self.async_show_form(
                    step_id="add_custom",
                    errors={"base": "保存失败，请检查日志"},
                )

            _LOGGER.info("已添加自定义假期: %s (%s)", name, date_str)
            return await self.async_step_menu()

        return self.async_show_form(
            step_id="add_custom",
            data_schema=vol.Schema({
                vol.Required(CONF_CUSTOM_NAME): selector.TextSelector(),
                vol.Required(CONF_CUSTOM_DATE): selector.DateSelector(),
            }),
            description_placeholders={
                "tips": "⭐ **添加自定义假期**：输入名称和日期（单日）",
            },
        )

    @override
    async def async_step_finish(self) -> ConfigFlowResult:
        """完成步骤：保存并重载"""
        return self.async_create_entry(title="", data={})

    # ---------- 辅助方法 ----------

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
            f"  • 📅 法定假期：{'✅ 启用' if flags[CONF_ENABLED_LEGAL] else '❌ 禁用'}（自动导入）\n"
            f"  • 🎓 学生假期：{'✅ 启用' if flags[CONF_ENABLED_STUDENT] else '❌ 禁用'}\n"
            f"  • ⭐ 自定义假期：{'✅ 启用' if flags[CONF_ENABLED_CUSTOM] else '❌ 禁用'}\n"
            "\n💡 保存后可在菜单中添加学生假期 / 自定义假期。"
        )

    @staticmethod
    def _get_student_type(value: str) -> Optional[Dict[str, Any]]:
        """根据 label 查找学生假期类型配置"""
        for t in STUDENT_HOLIDAY_TYPES:
            if t["label"] == value:
                return t
        return None
