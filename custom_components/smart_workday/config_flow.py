"""Config flow for Smart Workday.

v3.0.0 破坏性重构：
- 顶层开关 3 → 2：删除 enabled_student
- OptionsFlow 5 → 3 步：
    init          - 状态摘要 + 下拉路由
    toggle_switch - 2 开关合一
    add_holiday   - 添加假期（合并学生/自定义，表单顶部选类别）
    finish        - reload
- 类别：下拉快捷选项 + 可自定义输入（SelectSelector + custom_value=True）
  默认推荐：学生 / 工作 / 个人 / 家庭，用户可输入任意新值
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
    CONF_ENABLED_CUSTOM,
    CONF_NAME,
    CONF_START_DATE,
    CONF_END_DATE,
    CONF_CUSTOM_NAME,
    CONF_CATEGORY,
    DEFAULT_CUSTOM_CATEGORIES,
    KEY_LEGAL,
    KEY_CUSTOM,
    empty_calendar_data,
)

_LOGGER = logging.getLogger(__name__)

# 顶层开关字段名（v3.0.0 起仅 2 个）
_SWITCH_KEYS = (CONF_ENABLED_LEGAL, CONF_ENABLED_CUSTOM)


def _switch_schema(defaults: Optional[Dict[str, bool]] = None) -> Dict:
    """构造 2 个顶层开关的 vol.Schema 字段映射。"""
    defaults = defaults or {}
    return {
        vol.Required(key, default=defaults.get(key, True)): selector.BooleanSelector()
        for key in _SWITCH_KEYS
    }


def _parse_switch_input(user_input: Dict[str, Any]) -> Dict[str, bool]:
    """从 user_input 提取 2 个开关的值。"""
    return {key: bool(user_input[key]) for key in _SWITCH_KEYS}


# ============================================================
# ConfigFlow - 首次添加集成（名称 + 2 个顶层开关）
# ============================================================

class SmartWorkdayConfigFlow(ConfigFlow, domain=DOMAIN):
    """首次添加：集成名称 + 2 个顶层启用开关，一步完成。"""

    VERSION = 2  # v3.0.0：ConfigFlow VERSION 也升位，让老 entry 走 schema migration

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry):
        return SmartWorkdayOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """唯一一步：集成名称 + 2 个顶层启用开关"""
        if user_input is not None:
            name = (user_input.get(CONF_NAME) or DEFAULT_NAME).strip() or DEFAULT_NAME
            data = {CONF_NAME: name}
            data.update(_parse_switch_input(user_input))
            return self.async_create_entry(title=name, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
                **_switch_schema(),
            }),
            description_placeholders={
                "tips": (
                    "⚙️ 输入集成名称，并选择要启用的假期类型（全部默认启用）。\n"
                    "💡 保存后会跳到选项配置页面，可录入自定义假期（带类别）。"
                ),
            },
        )


# ============================================================
# OptionsFlow - 总控台
# ============================================================

class SmartWorkdayOptionsFlow(OptionsFlowWithReload):
    """v3.0.0：3 步 —— init / toggle_switch / add_holiday / finish

    ⚠️ 不覆盖 __init__：HA 会自动注入 self.config_entry。
    """

    @override
    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        """总控台：状态摘要 + 「下一步操作」下拉框。"""
        if user_input is not None:
            action = user_input.get("action", "")
            if action == "toggle_switch":
                return await self.async_step_toggle_switch()
            if action == "add_holiday":
                return await self.async_step_add_holiday()
            if action == "finish":
                return await self.async_step_finish()
            return await self.async_step_init()

        flags = self._get_flags()
        data = await self._get_calendar_data()
        custom_categories = self._get_categories_summary(data)

        status = (
            "📊 **当前配置**\n"
            f"  • 📅 法定假期：{'✅ 启用' if flags[CONF_ENABLED_LEGAL] else '❌ 禁用'}（{len(data.get(KEY_LEGAL, []))} 条）\n"
            f"  • 🎉 自定义假期：{'✅ 启用' if flags[CONF_ENABLED_CUSTOM] else '❌ 禁用'}（{len(data.get(KEY_CUSTOM, []))} 条）\n"
            f"  • 🏷️ 类别：{custom_categories}\n"
            "\n📌 **操作说明**\n"
            "  • 法定假期自动从国务院通知导入，无需手动录入\n"
            "  • 添加假期：下拉选类别（学生/工作/个人/家庭，或输入新类别）\n"
            "  • 删除事件：在日历实体上操作"
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("action", default="add_holiday"): selector.SelectSelector({
                    "options": [
                        {"value": "add_holiday", "label": "🎉 添加假期"},
                        {"value": "toggle_switch", "label": "⚙️ 开关管理"},
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
        """开关管理：一次改 2 个开关。"""
        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data.update(_parse_switch_input(user_input))
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return await self.async_step_init()

        flags = self._get_flags()
        return self.async_show_form(
            step_id="toggle_switch",
            data_schema=vol.Schema(_switch_schema(defaults=flags)),
            description_placeholders={
                "tips": "⚙️ **开关管理**\n"
                        "📅 法定假期：启用后自动从国务院通知导入当年数据\n"
                        "🎉 自定义假期：启用后可添加带类别的自定义假期",
            },
        )

    @override
    async def async_step_add_holiday(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """添加假期（合并学生/自定义）：类别 + 名称 + 开始 + 结束。

        类别字段：SelectSelector with custom_value=True，
        提供学生/工作/个人/家庭 4 个快捷选项，同时允许用户输入任意新类别。
        """
        if user_input is not None:
            category = (user_input.get(CONF_CATEGORY) or "自定义").strip() or "自定义"
            name = (user_input.get(CONF_CUSTOM_NAME) or "").strip()
            start = user_input.get(CONF_START_DATE)
            end = user_input.get(CONF_END_DATE)
            if not name:
                return self.async_show_form(
                    step_id="add_holiday",
                    errors={"base": "请填写假期名称"},
                )
            if not start:
                return self.async_show_form(
                    step_id="add_holiday",
                    errors={"base": "请选择开始日期"},
                )
            end_str = end if end else start
            dm = self._get_data_manager()
            ok = await dm.add_entry(name=name, start=start, end=end_str, category=category)
            if not ok:
                return self.async_show_form(
                    step_id="add_holiday",
                    errors={"base": "保存失败，请检查日志"},
                )
            _LOGGER.info("已添加自定义假期: [%s] %s (%s ~ %s)", category, name, start, end_str)
            return await self.async_step_init()

        # 类别下拉 + 可自定义输入
        category_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=DEFAULT_CUSTOM_CATEGORIES,
                mode=selector.SelectSelectorMode.DROPDOWN,
                custom_value=True,
            )
        )

        return self.async_show_form(
            step_id="add_holiday",
            data_schema=vol.Schema({
                vol.Required(CONF_CATEGORY, default=DEFAULT_CUSTOM_CATEGORIES[0]): category_selector,
                vol.Required(CONF_CUSTOM_NAME): selector.TextSelector(),
                vol.Required(CONF_START_DATE): selector.DateSelector(),
                vol.Optional(CONF_END_DATE): selector.DateSelector(),
            }),
            description_placeholders={
                "tips": "🎉 **添加自定义假期**\n"
                        "选择类别（可选：学生/工作/个人/家庭，也可输入新类别）\n"
                        "填写名称和日期范围。留空结束日期表示单日事件。",
            },
        )

    @override
    async def async_step_finish(self) -> ConfigFlowResult:
        """完成：保存并重载。"""
        return self.async_create_entry(title="", data={})

    # ---------- 辅助方法 ----------

    def _get_flags(self) -> Dict[str, bool]:
        """读取当前 entry.data 中的开关"""
        d = self.config_entry.data
        return {
            CONF_ENABLED_LEGAL: bool(d.get(CONF_ENABLED_LEGAL, True)),
            CONF_ENABLED_CUSTOM: bool(d.get(CONF_ENABLED_CUSTOM, True)),
        }

    def _get_data_manager(self):
        return self.hass.data[DOMAIN][self.config_entry.entry_id]["data_manager"]

    async def _get_calendar_data(self) -> Dict[str, Any]:
        """读取所有日历数据（用于状态摘要）"""
        try:
            return await self._get_data_manager().load_calendar_data()
        except Exception:
            return empty_calendar_data()

    @staticmethod
    def _get_categories_summary(data: Dict[str, Any]) -> str:
        """汇总当前 custom 条目里的所有类别（按出现顺序）。"""
        categories: list[str] = []
        for item in data.get(KEY_CUSTOM, []):
            cat = item.get("category")
            if cat and cat not in categories:
                categories.append(cat)
        if not categories:
            return "（暂无）"
        return "、".join(categories)
