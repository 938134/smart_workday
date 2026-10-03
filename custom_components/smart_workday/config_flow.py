"""Config flow for Smart Workday.

方案 X（v2.13.0）+ 学生/自定义统一（v2.14.0）：
- ConfigFlow：1 步 4 字段（集成名称 + 3 个顶层启用开关）
- OptionsFlow 总控台（5 步）：
    init            - 状态摘要 + 下拉路由
    toggle_switch   - 3 开关合一
    add_student     - 学生假期（名称 + 开始日期 + 结束日期可选）
    add_custom      - 自定义假期（名称 + 开始日期 + 结束日期可选）
    finish          - reload

学生假期和自定义假期 UI 结构完全一致，仅数据分类不同（studentdays vs customdays）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, override

import voluptuous as vol
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
    CONF_START_DATE,
    CONF_END_DATE,
    CONF_CUSTOM_NAME,
)

_LOGGER = logging.getLogger(__name__)


# ============================================================
# ConfigFlow - 首次添加集成（名称 + 3 个顶层开关）
# ============================================================

class SmartWorkdayConfigFlow(ConfigFlow, domain=DOMAIN):
    """首次添加：集成名称 + 3 个顶层启用开关，一步完成。

    提交后 HA 自动跳到 OptionsFlow，用户可继续录入学生/自定义假期。
    """

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry):
        return SmartWorkdayOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """唯一一步：集成名称 + 3 个顶层启用开关"""
        if user_input is not None:
            name = (user_input.get(CONF_NAME) or DEFAULT_NAME).strip() or DEFAULT_NAME
            return self.async_create_entry(title=name, data={
                CONF_NAME: name,
                CONF_ENABLED_LEGAL: bool(user_input[CONF_ENABLED_LEGAL]),
                CONF_ENABLED_STUDENT: bool(user_input[CONF_ENABLED_STUDENT]),
                CONF_ENABLED_CUSTOM: bool(user_input[CONF_ENABLED_CUSTOM]),
            })

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
                    "⚙️ 输入集成名称，并选择要启用的假期类型（全部默认启用）。\n"
                    "💡 保存后会跳到选项配置页面，可录入学生假期和自定义假期。"
                ),
            },
        )


# ============================================================
# OptionsFlow - 总控台（总入口 + 按需跳转）
# ============================================================

class SmartWorkdayOptionsFlow(OptionsFlowWithReload):
    """方案 X（v2.13.0）+ 学生/自定义统一（v2.14.0）：

    步骤：
    1. init            - 总控台（状态摘要 + 下拉路由）
    2. toggle_switch   - 3 开关合一
    3. add_student     - 学生假期：名称 + 开始日期 + 结束日期（可选，与 add_custom 统一）
    4. add_custom      - 自定义假期：名称 + 开始日期 + 结束日期（可选）
    5. finish          - 保存并重载

    ⚠️ 不覆盖 __init__：HA 会自动注入 self.config_entry。
    """

    @override
    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        """总控台：状态摘要 + 「下一步操作」下拉框。

        放弃 async_show_menu（不同 HA 版本 menu 标签翻译路径不一致，导致按钮空文字）。
        改用 async_show_form + SelectSelector：选项标签直接来自 options 数组，翻译 100% 稳定。
        """
        # 用户已选择动作 → 路由
        if user_input is not None:
            action = user_input.get("action", "")
            if action == "toggle_switch":
                return await self.async_step_toggle_switch()
            if action == "add_student":
                return await self.async_step_add_student()
            if action == "add_custom":
                return await self.async_step_add_custom()
            if action == "finish":
                return await self.async_step_finish()
            return await self.async_step_init()

        flags = self._get_flags()
        data = await self._get_calendar_data()

        status = (
            "📊 **当前配置**\n"
            f"  • 📅 法定假期：{'✅ 启用' if flags[CONF_ENABLED_LEGAL] else '❌ 禁用'}（{len(data.get('holidays', []))} 条）\n"
            f"  • 🎓 学生假期：{'✅ 启用' if flags[CONF_ENABLED_STUDENT] else '❌ 禁用'}（{len(data.get('studentdays', []))} 条）\n"
            f"  • ⭐ 自定义假期：{'✅ 启用' if flags[CONF_ENABLED_CUSTOM] else '❌ 禁用'}（{len(data.get('customdays', []))} 条）\n"
            "\n📌 **操作说明**\n"
            "  • 法定假期自动从国务院通知导入，无需手动录入\n"
            "  • 删除事件：在日历实体上操作\n"
            "  • 请在下方「下一步操作」下拉框中选择要执行的动作"
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("action", default="toggle_switch"): selector.SelectSelector({
                    "options": [
                        {"value": "toggle_switch", "label": "⚙️ 开关管理（启停三类假期）"},
                        {"value": "add_student", "label": "🎓 添加学生假期"},
                        {"value": "add_custom", "label": "⭐ 添加自定义假期"},
                        {"value": "finish", "label": "✅ 完成并保存"},
                    ],
                    "mode": "dropdown",
                }),
            }),
            description_placeholders={"status": status},
        )

    @override
    async def async_step_toggle_switch(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """开关管理：一次改 3 个开关"""
        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data[CONF_ENABLED_LEGAL] = bool(user_input[CONF_ENABLED_LEGAL])
            new_data[CONF_ENABLED_STUDENT] = bool(user_input[CONF_ENABLED_STUDENT])
            new_data[CONF_ENABLED_CUSTOM] = bool(user_input[CONF_ENABLED_CUSTOM])
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return await self.async_step_init()

        flags = self._get_flags()
        return self.async_show_form(
            step_id="toggle_switch",
            data_schema=vol.Schema({
                vol.Required(CONF_ENABLED_LEGAL, default=flags[CONF_ENABLED_LEGAL]):
                    selector.BooleanSelector(),
                vol.Required(CONF_ENABLED_STUDENT, default=flags[CONF_ENABLED_STUDENT]):
                    selector.BooleanSelector(),
                vol.Required(CONF_ENABLED_CUSTOM, default=flags[CONF_ENABLED_CUSTOM]):
                    selector.BooleanSelector(),
            }),
            description_placeholders={
                "tips": "⚙️ **开关管理**\n"
                        "📅 法定假期：启用后自动从国务院通知导入当年数据\n"
                        "🎓 学生假期：启用后可在日历上添加（选类型 + 日期）\n"
                        "⭐ 自定义假期：启用后可添加任意名称的单日假期",
            },
        )

    @override
    async def async_step_add_student(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """学生假期：名称 + 开始日期 + 结束日期（可选）"""
        return await self._handle_add_holiday(
            step_id="add_student",
            category="studentdays",
            tips="🎓 **添加学生假期**\n填写名称和日期范围。留空结束日期表示单日事件。",
            log_label="学生假期",
            user_input=user_input,
        )

    @override
    async def async_step_add_custom(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """自定义假期：名称 + 开始日期 + 结束日期（可选）"""
        return await self._handle_add_holiday(
            step_id="add_custom",
            category="customdays",
            tips="⭐ **添加自定义假期**\n填写名称和日期范围。留空结束日期表示单日事件。",
            log_label="自定义假期",
            user_input=user_input,
        )

    async def _handle_add_holiday(
        self,
        step_id: str,
        category: str,
        tips: str,
        log_label: str,
        user_input: Optional[Dict[str, Any]] = None,
    ) -> ConfigFlowResult:
        """学生/自定义假期通用处理器（UI 结构完全一致，仅数据分类不同）。

        - 只填开始日期 → 单日事件（end = start）
        - 填开始 + 结束日期 → 范围事件
        - 名称自由输入
        """
        if user_input is not None:
            name = (user_input.get(CONF_CUSTOM_NAME) or "").strip()
            start = user_input.get(CONF_START_DATE)
            end = user_input.get(CONF_END_DATE)
            if not name:
                return self.async_show_form(
                    step_id=step_id,
                    errors={"base": "请填写假期名称"},
                )
            if not start:
                return self.async_show_form(
                    step_id=step_id,
                    errors={"base": "请选择开始日期"},
                )
            # 结束日期为空 → 视为单日（end = start）
            end_str = end if end else start
            dm = self._get_data_manager()
            ok = await dm.add_entry(category, name, start, end_str)
            if not ok:
                return self.async_show_form(
                    step_id=step_id,
                    errors={"base": "保存失败，请检查日志"},
                )
            _LOGGER.info("已添加%s: %s (%s ~ %s)", log_label, name, start, end_str)
            return await self.async_step_init()

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({
                vol.Required(CONF_CUSTOM_NAME): selector.TextSelector(),
                vol.Required(CONF_START_DATE): selector.DateSelector(),
                vol.Optional(CONF_END_DATE): selector.DateSelector(),
            }),
            description_placeholders={"tips": tips},
        )

    @override
    async def async_step_finish(self) -> ConfigFlowResult:
        """完成：保存并重载（OptionsFlowWithReload 自动触发 reload）"""
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

    def _get_data_manager(self):
        return self.hass.data[DOMAIN][self.config_entry.entry_id]["data_manager"]

    async def _get_calendar_data(self) -> Dict[str, Any]:
        """读取所有日历数据（用于状态摘要）"""
        try:
            return await self._get_data_manager().load_calendar_data()
        except Exception:
            return {"holidays": [], "studentdays": [], "customdays": []}
