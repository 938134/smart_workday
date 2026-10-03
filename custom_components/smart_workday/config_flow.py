"""Config flow for Smart Workday.

方案 B（v2.12.0）：
- ConfigFlow：1 步，只填「集成名称」
- OptionsFlow 总控台：
    init（总控台菜单）
    ├── toggle_switch（3 开关合一）
    ├── add_student_type（选类型）→ add_student_date（填日期，仅范围型）
    ├── add_custom（名称+日期）
    └── finish（reload）
"""

from __future__ import annotations

import logging
from datetime import date
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
# ConfigFlow - 首次添加集成（仅填名称）
# ============================================================

class SmartWorkdayConfigFlow(ConfigFlow, domain=DOMAIN):
    """首次添加：只填集成名称。

    所有开关/录入都放在 OptionsFlow 里，ConfigFlow 不再承担配置职责。
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
        """唯一一步：只填集成名称"""
        if user_input is not None:
            name = (user_input.get(CONF_NAME) or DEFAULT_NAME).strip() or DEFAULT_NAME
            return self.async_create_entry(title=name, data={CONF_NAME: name})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
            }),
            description_placeholders={
                "tips": (
                    "⚙️ 输入设备名称（可在 Options Flow 中随时修改配置）。\n"
                    "💡 保存后会跳到选项配置页面，可设置假期开关并录入假期。"
                ),
            },
        )


# ============================================================
# OptionsFlow - 总控台（总入口 + 按需跳转）
# ============================================================

class SmartWorkdayOptionsFlow(OptionsFlowWithReload):
    """总控台式选项流。

    步骤：
    1. init            - 总控台菜单（显示状态摘要 + 4 个动作）
    2. toggle_switch   - 3 个开关合一管理（一次改所有）
    3. add_student_type- 学生假期选类型 → 转 add_student_date
    4. add_student_date- 学生假期范围型填日期（儿童节跳过此步）
    5. add_custom      - 添加自定义假期（名称+日期）
    6. finish          - 保存并重载

    ⚠️ 不覆盖 __init__：HA 会自动注入 self.config_entry。
    """

    @override
    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        """总控台：状态摘要 + 4 个动作按钮。

        用 async_show_menu 显示 4 个动作按钮，HA 会用
        `options.step.<option_id>.title` 查翻译（我们已定义），按钮文案稳定渲染。
        """
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
            "  • 点击下方按钮进行对应操作"
        )

        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "toggle_switch",
                "add_student_type",
                "add_custom",
                "finish",
            ],
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
    async def async_step_add_student_type(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """学生假期选类型（HA 下拉表单，一次完成）

        - 选「🎉 儿童节」：自动用当年 6/1 保存，无需填日期
        - 其他类型：跳转到 add_student_date 填 start/end
        """
        if user_input is None:
            return self.async_show_form(
                step_id="add_student_type",
                data_schema=vol.Schema({
                    vol.Required(CONF_STUDENT_TYPE): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[t["value"] for t in STUDENT_HOLIDAY_TYPES],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            translation_key="student_type",
                        )
                    ),
                }),
                description_placeholders={
                    "tips": (
                        "🎓 **选择学生假期类型**\n"
                        "  • 🎉 儿童节：自动设为当年 6 月 1 日，无需填日期\n"
                        "  • 其他类型：进入下一步填写日期范围"
                    ),
                },
            )

        type_cfg = self._get_student_type(user_input.get(CONF_STUDENT_TYPE))
        if type_cfg is None:
            return await self.async_step_init()

        current_year = date.today().year
        name_base = type_cfg["label"].split(" ", 1)[-1]
        name = f"{current_year} {name_base}"
        dm = self._get_data_manager()

        # 单日型（儿童节）：自动 6/1 保存，无需再进表单
        if type_cfg["single_day"]:
            date_str = f"{current_year}-{CHILDREN_DAY_MONTH:02d}-{CHILDREN_DAY_DAY:02d}"
            ok = await dm.add_entry("studentdays", name, date_str, date_str)
            if not ok:
                return self.async_show_form(
                    step_id="add_student_type",
                    errors={"base": "保存失败，请检查日志"},
                )
            _LOGGER.info("已添加学生假期: %s", name)
            return await self.async_step_init()

        # 范围型：进入日期表单
        self._current_student_type_value = type_cfg["value"]
        self._current_student_type_name = name
        return await self.async_step_add_student_date()

    @override
    async def async_step_add_student_date(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """学生假期填日期（仅范围型）"""
        if user_input is not None:
            start = user_input.get(CONF_START_DATE)
            end = user_input.get(CONF_END_DATE)
            if not start or not end:
                return self.async_show_form(
                    step_id="add_student_date",
                    errors={"base": "请填写开始和结束日期"},
                )
            name = getattr(self, "_current_student_type_name", "学生假期")
            dm = self._get_data_manager()
            ok = await dm.add_entry("studentdays", name, start, end)
            if not ok:
                return self.async_show_form(
                    step_id="add_student_date",
                    errors={"base": "保存失败，请检查日志"},
                )
            _LOGGER.info("已添加学生假期: %s (%s ~ %s)", name, start, end)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="add_student_date",
            data_schema=vol.Schema({
                vol.Required(CONF_START_DATE): selector.DateSelector(),
                vol.Required(CONF_END_DATE): selector.DateSelector(),
            }),
            description_placeholders={
                "tips": "📅 **填写日期范围**",
            },
        )

    @override
    async def async_step_add_custom(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """自定义假期：名称 + 日期（单日）"""
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
            dm = self._get_data_manager()
            ok = await dm.add_entry("customdays", name, date_str, date_str)
            if not ok:
                return self.async_show_form(
                    step_id="add_custom",
                    errors={"base": "保存失败，请检查日志"},
                )
            _LOGGER.info("已添加自定义假期: %s (%s)", name, date_str)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="add_custom",
            data_schema=vol.Schema({
                vol.Required(CONF_CUSTOM_NAME): selector.TextSelector(),
                vol.Required(CONF_CUSTOM_DATE): selector.DateSelector(),
            }),
            description_placeholders={
                "tips": "⭐ **添加自定义假期**\n"
                        "填写名称和日期（单日）。纪念日、生日等个人日期都归此类。",
            },
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

    @staticmethod
    def _get_student_type(value: str) -> Optional[Dict[str, Any]]:
        """根据 value 查找学生假期类型配置"""
        for t in STUDENT_HOLIDAY_TYPES:
            if t["value"] == value:
                return t
        return None
