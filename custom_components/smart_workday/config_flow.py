"""Config flow for Smart Workday.

参照 HA 官方 holiday 集成的模式重写：
- 使用 OptionsFlowWithReload 自动处理 reload
- 使用 domain=DOMAIN 关键字参数声明 domain
- 使用 @staticmethod @callback @override 装饰链
- OptionsFlow.__init__ 通过 super() 让基类自动设置 self.config_entry
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, override

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.storage import Store

import uuid
from .const import (
    DOMAIN, DEFAULT_NAME, HolidayMode,
    LEGAL_HOLIDAY_PRESETS, STUDENT_HOLIDAY_DEFAULTS, StudentHolidayType,
)
from .coordinator import STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


# ---------- 表单选项构建器 ----------

def _build_mode_options() -> List[selector.SelectOptionDict]:
    """构建假期模式选项列表"""
    return [
        selector.SelectOptionDict(
            value=mode.value,
            label=f"{mode.icon} {mode.display_name} - {mode.description}",
        )
        for mode in HolidayMode
    ]


def _build_main_menu_options() -> List[selector.SelectOptionDict]:
    """主菜单操作选项"""
    return [
        selector.SelectOptionDict(value="legal", label="📅 法定节假日管理"),
        selector.SelectOptionDict(value="student", label="🎓 学生假期管理"),
        selector.SelectOptionDict(value="custom", label="⭐ 自定义节假日管理"),
        selector.SelectOptionDict(value="mode", label="⚙️ 假期模式设置"),
        selector.SelectOptionDict(value="advanced", label="📝 高级 JSON 编辑"),
        selector.SelectOptionDict(value="back", label="↩️ 完成配置"),
    ]


def _build_legal_actions() -> List[selector.SelectOptionDict]:
    """法定节假日操作选项"""
    return [
        selector.SelectOptionDict(value="import", label="📥 从 2026 国务院通知导入（覆盖）"),
        selector.SelectOptionDict(value="add", label="➕ 手动添加一条"),
        selector.SelectOptionDict(value="delete", label="🗑️ 删除某条"),
        selector.SelectOptionDict(value="clear", label="⚠️ 清空全部"),
        selector.SelectOptionDict(value="back", label="⬅️ 返回主菜单"),
    ]


def _build_custom_actions() -> List[selector.SelectOptionDict]:
    """自定义节假日操作选项"""
    return [
        selector.SelectOptionDict(value="add", label="➕ 添加一条"),
        selector.SelectOptionDict(value="delete", label="🗑️ 删除某条"),
        selector.SelectOptionDict(value="clear", label="⚠️ 清空全部"),
        selector.SelectOptionDict(value="back", label="⬅️ 返回主菜单"),
    ]


def _build_confirm_options(default: str = "cancel") -> List[selector.SelectOptionDict]:
    """确认对话框选项（默认选中取消，避免误操作）"""
    return [
        selector.SelectOptionDict(value="cancel", label="❌ 取消"),
        selector.SelectOptionDict(value="confirm", label="✅ 确认执行"),
    ]


def _build_legal_type_options() -> List[selector.SelectOptionDict]:
    """法定节假日类型选项（放假/调休上班）"""
    return [
        selector.SelectOptionDict(value="off", label="🌴 放假"),
        selector.SelectOptionDict(value="work", label="💼 调休上班"),
    ]


def _build_year_options() -> List[selector.SelectOptionDict]:
    """预置数据的年份选项"""
    return [
        selector.SelectOptionDict(
            value=str(year), label=f"{year} 年国务院通知"
        )
        for year in sorted(LEGAL_HOLIDAY_PRESETS.keys())
    ]


# ---------- 数据格式化辅助 ----------

def _format_legal_list(items: List[Dict]) -> str:
    """格式化法定节假日列表为 markdown 文本"""
    if not items:
        return "_暂无法定节假日数据_\n\n💡 建议使用「📥 从 2026 国务院通知导入」快速填充"
    lines = []
    grouped: Dict[str, List[Dict]] = {}
    for item in items:
        name = item.get("name", "?")
        key = "调休" if "调休" in name else name
        grouped.setdefault(key, []).append(item)
    for name, entries in grouped.items():
        dates = sorted([e.get("date", "") for e in entries])
        lines.append(f"• **{name}**：{', '.join(dates)}")
    return "\n".join(lines[:15]) + (f"\n\n... 共 {len(items)} 条" if len(items) > 15 else "")


def _format_custom_list(items: List[Dict]) -> str:
    """格式化自定义节假日列表"""
    if not items:
        return "_暂无自定义节假日_"
    return "\n".join([f"• {i.get('name', '?')}：{i.get('date', i.get('start', '?'))}" for i in items])


def _format_student_summary(data: Dict) -> str:
    """格式化学生假期当前状态"""
    lines = []
    for item in data.get("studentdays", []):
        enabled = item.get("enabled", True)
        stype = item.get("type", "?")
        name = item.get("name", "?")
        status = "✅ 启用" if enabled else "❌ 禁用"
        if "date" in item:
            lines.append(f"• {name}（{stype}）：{status} - {item.get('date', '未设置')}")
        else:
            lines.append(f"• {name}（{stype}）：{status} - {item.get('start', '未设置')} ~ {item.get('end', '未设置')}")
    if not lines:
        return "_尚未配置学生假期_"
    return "\n".join(lines)


class SmartWorkdayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Smart Workday 配置流 - 处理首次添加集成"""

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry):
        """获取选项流"""
        return SmartWorkdayOptionsFlow(config_entry)

    @override
    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """第一步：输入名称和选择模式"""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input.get("name", DEFAULT_NAME),
                data={
                    "name": user_input.get("name", DEFAULT_NAME),
                    "holiday_mode": user_input.get(
                        "holiday_mode", HolidayMode.STANDARD.value
                    ),
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=DEFAULT_NAME): selector.TextSelector(),
                    vol.Required(
                        "holiday_mode", default=HolidayMode.STANDARD.value
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_build_mode_options(), mode="dropdown"
                        )
                    ),
                }
            ),
        )


class SmartWorkdayOptionsFlow(OptionsFlowWithReload):
    """选项流 - 主菜单 + 高级 JSON 编辑

    继承 OptionsFlowWithReload：调用 async_create_entry 时 HA 会自动 reload entry
    """

    def __init__(self, config_entry: ConfigEntry):
        """初始化选项流 - 必须调用 super().__init__() 让基类设置 self.config_entry"""
        super().__init__(config_entry)
        self._data: Dict[str, List] = {}

    def _get_store(self) -> Store:
        """获取当前条目的 Store 实例"""
        return Store(
            self.hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{self.config_entry.entry_id}",
        )

    async def _load_data(self) -> Dict[str, List]:
        """从 Store 加载数据"""
        try:
            store = self._get_store()
            data = await store.async_load()
            if not isinstance(data, dict):
                data = {}
            data.setdefault("holidays", [])
            data.setdefault("customdays", [])
            data.setdefault("studentdays", [])
            for key in ("holidays", "customdays", "studentdays"):
                if not isinstance(data[key], list):
                    data[key] = []
            return data
        except Exception as e:
            _LOGGER.error("加载数据失败: %s", e)
            return {"holidays": [], "customdays": [], "studentdays": []}

    async def _save_data(self, data: Dict) -> bool:
        """保存数据到 Store"""
        try:
            store = self._get_store()
            for key in ("holidays", "customdays", "studentdays"):
                data[key].sort(key=lambda x: x.get("date") or x.get("start", ""))
            await store.async_save(data)
            _LOGGER.info("数据保存成功")
            return True
        except Exception as e:
            _LOGGER.error("保存数据失败: %s", e)
            return False

    def _update_entry_mode(self, mode_value: str) -> None:
        """更新 entry.data 中的假期模式（同步方法，OptionsFlowWithReload 会在
        async_create_entry 后自动 reload）"""
        new_data = dict(self.config_entry.data)
        new_data["holiday_mode"] = mode_value
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=new_data
        )

    # ---------- 主菜单 ----------

    @override
    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """主菜单：显示统计 + 5 个入口"""
        if not self._data:
            self._data = await self._load_data()

        if user_input is not None:
            action = user_input.get("action")
            if action == "legal":
                return await self.async_step_legal()
            elif action == "student":
                return await self.async_step_student()
            elif action == "custom":
                return await self.async_step_custom()
            elif action == "mode":
                return await self.async_step_mode()
            elif action == "advanced":
                return await self.async_step_advanced()
            # back 或其他：结束流程
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_build_main_menu_options(), mode="list"
                        )
                    ),
                }
            ),
            description_placeholders={"stats": self._build_stats_text()},
        )

    def _build_stats_text(self) -> str:
        """构建当前假期统计文本"""
        h_count = len(self._data.get("holidays", []))
        c_count = len(self._data.get("customdays", []))
        s_count = len(self._data.get("studentdays", []))
        s_enabled = sum(1 for i in self._data.get("studentdays", []) if i.get("enabled", True))
        current_mode = self.config_entry.data.get("holiday_mode", HolidayMode.STANDARD.value)
        mode_obj = next((m for m in HolidayMode if m.value == current_mode), HolidayMode.STANDARD)
        return (
            f"📊 **当前配置统计**\n"
            f"  • 📅 法定节假日：{h_count} 条\n"
            f"  • 🎓 学生假期：{s_enabled}/{s_count} 启用\n"
            f"  • ⭐ 自定义节假日：{c_count} 条\n"
            f"  • ⚙️ 当前模式：{mode_obj.display_name}\n"
            f"\n📝 下方选择要管理的项目，进入后点「⬅️ 返回主菜单」继续。"
        )

    # ---------- 法定节假日管理 ----------

    async def async_step_legal(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """法定节假日列表 + 操作入口"""
        if user_input is not None:
            action = user_input.get("action")
            if action == "import":
                return await self.async_step_legal_import()
            elif action == "add":
                return await self.async_step_legal_add()
            elif action == "delete":
                return await self.async_step_legal_delete()
            elif action == "clear":
                return await self.async_step_legal_clear()
            elif action == "back":
                return await self.async_step_init()

        items = self._data.get("holidays", [])
        return self.async_show_form(
            step_id="legal",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_build_legal_actions(), mode="list"
                        )
                    ),
                }
            ),
            description_placeholders={
                "list": _format_legal_list(items),
                "count": str(len(items)),
            },
        )

    async def async_step_legal_import(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """从预置数据导入法定节假日"""
        if user_input is not None:
            try:
                year = int(user_input.get("year"))
            except (ValueError, TypeError):
                year = 2026
            if user_input.get("confirm") != "confirm":
                return await self.async_step_legal()

            presets = LEGAL_HOLIDAY_PRESETS.get(year, [])
            self._data["holidays"] = [
                {
                    "name": item["name"],
                    "date": item["date"],
                    "uid": str(uuid.uuid4())[:8],
                }
                for item in presets
            ]
            if await self._save_data(self._data):
                return await self.async_step_legal()

            return self.async_show_form(
                step_id="legal_import",
                data_schema=self._legal_import_schema(),
                errors={"base": "save_failed"},
                description_placeholders=self._legal_import_desc(),
            )

        return self.async_show_form(
            step_id="legal_import",
            data_schema=self._legal_import_schema(),
            description_placeholders=self._legal_import_desc(),
        )

    def _legal_import_schema(self) -> vol.Schema:
        """法定节假日导入表单"""
        return vol.Schema(
            {
                vol.Required("year", default="2026"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_build_year_options(), mode="dropdown"
                    )
                ),
                vol.Required("confirm", default="confirm"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_build_confirm_options(default="confirm"), mode="list"
                    )
                ),
            }
        )

    def _legal_import_desc(self) -> Dict[str, str]:
        """导入步骤描述"""
        years = ", ".join(str(y) for y in sorted(LEGAL_HOLIDAY_PRESETS.keys()))
        return {
            "warning": f"⚠️ 导入将覆盖当前所有法定节假日数据。\n支持年份：{years}",
        }

    async def async_step_legal_add(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """手动添加法定节假日"""
        errors: Dict[str, str] = {}

        if user_input is not None:
            name = (user_input.get("name") or "").strip()
            date_val = user_input.get("date")
            date_str = date_val if isinstance(date_val, str) else (date_val.isoformat() if date_val else "")
            htype = user_input.get("type", "off")
            if not name or not date_str:
                errors["base"] = "missing_required"
            else:
                if htype == "work" and "调休" not in name:
                    name = f"{name}调休上班"
                entry = {
                    "name": name,
                    "date": date_str,
                    "uid": str(uuid.uuid4())[:8],
                }
                self._data.setdefault("holidays", []).append(entry)
                if await self._save_data(self._data):
                    return await self.async_step_legal()
                errors["base"] = "save_failed"

        return self.async_show_form(
            step_id="legal_add",
            data_schema=self._legal_add_schema(),
            errors=errors,
        )

    def _legal_add_schema(self) -> vol.Schema:
        """法定节假日添加表单"""
        return vol.Schema(
            {
                vol.Required("name", default="新假期"): selector.TextSelector(),
                vol.Required("date"): selector.DateSelector(),
                vol.Required("type", default="off"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_build_legal_type_options(), mode="list"
                    )
                ),
            }
        )

    async def async_step_legal_delete(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """删除法定节假日条目"""
        items = self._data.get("holidays", [])
        if not items:
            return await self.async_step_legal()

        if user_input is not None:
            uid = user_input.get("uid")
            for i, item in enumerate(items):
                if item.get("uid") == uid:
                    items.pop(i)
                    break
            if await self._save_data(self._data):
                return await self.async_step_legal()

        options = [
            selector.SelectOptionDict(
                value=item.get("uid", ""),
                label=f"{item.get('name', '?')} ({item.get('date', '')})",
            )
            for item in items
        ]
        return self.async_show_form(
            step_id="legal_delete",
            data_schema=vol.Schema(
                {
                    vol.Required("uid"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, mode="dropdown")
                    ),
                }
            ),
        )

    async def async_step_legal_clear(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """清空法定节假日（带确认）"""
        if user_input is not None:
            if user_input.get("confirm") == "confirm":
                self._data["holidays"] = []
                await self._save_data(self._data)
            return await self.async_step_legal()

        return self.async_show_form(
            step_id="legal_clear",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default="cancel"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_build_confirm_options(default="cancel"), mode="list"
                        )
                    ),
                }
            ),
            description_placeholders={
                "warning": f"⚠️ 即将清空 {len(self._data.get('holidays', []))} 条法定节假日数据，此操作不可撤销。",
            },
        )

    # ---------- 学生假期管理 ----------

    async def async_step_student(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """学生假期 5 项 - 一次性表单"""
        if not self._data:
            self._data = await self._load_data()

        if user_input is not None:
            new_studentdays: List[Dict[str, Any]] = []
            for stype in StudentHolidayType:
                default = STUDENT_HOLIDAY_DEFAULTS.get(stype, {})
                enabled = bool(user_input.get(f"enable_{stype.value}", default.get("enabled", False)))
                entry: Dict[str, Any] = {
                    "type": stype.value,
                    "name": stype.display_name,
                    "enabled": enabled,
                    "uid": str(uuid.uuid4())[:8],
                }
                if stype.is_range:
                    start_val = user_input.get(f"{stype.value}_start")
                    end_val = user_input.get(f"{stype.value}_end")
                    start_str = start_val if isinstance(start_val, str) else (start_val.isoformat() if start_val else "")
                    end_str = end_val if isinstance(end_val, str) else (end_val.isoformat() if end_val else "")
                    if not enabled:
                        start_str = ""
                        end_str = ""
                    entry["start"] = start_str
                    entry["end"] = end_str
                else:
                    date_val = user_input.get(f"{stype.value}_date")
                    date_str = date_val if isinstance(date_val, str) else (date_val.isoformat() if date_val else "")
                    if not enabled:
                        date_str = ""
                    entry["date"] = date_str
                new_studentdays.append(entry)

            self._data["studentdays"] = new_studentdays
            if await self._save_data(self._data):
                return await self.async_step_init()

            return self.async_show_form(
                step_id="student",
                data_schema=self._student_schema(),
                errors={"base": "save_failed"},
            )

        return self.async_show_form(
            step_id="student",
            data_schema=self._student_schema(),
        )

    def _student_schema(self) -> vol.Schema:
        """学生假期表单 - 5 项 checkbox + 日期"""
        current = {item.get("type"): item for item in self._data.get("studentdays", [])}
        schema_dict: Dict[Any, Any] = {}
        for stype in StudentHolidayType:
            item = current.get(stype.value, {})
            default_enabled = item.get(
                "enabled", STUDENT_HOLIDAY_DEFAULTS.get(stype, {}).get("enabled", False)
            )
            schema_dict[vol.Required(
                f"enable_{stype.value}", default=default_enabled
            )] = selector.BooleanSelector()

            if stype.is_range:
                schema_dict[vol.Required(
                    f"{stype.value}_start", default=item.get("start", "")
                )] = selector.DateSelector()
                schema_dict[vol.Required(
                    f"{stype.value}_end", default=item.get("end", "")
                )] = selector.DateSelector()
            else:
                schema_dict[vol.Required(
                    f"{stype.value}_date", default=item.get("date", "")
                )] = selector.DateSelector()

        return vol.Schema(schema_dict)

    # ---------- 自定义节假日管理 ----------

    async def async_step_custom(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """自定义节假日列表 + 操作入口"""
        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_custom_add()
            elif action == "delete":
                return await self.async_step_custom_delete()
            elif action == "clear":
                return await self.async_step_custom_clear()
            elif action == "back":
                return await self.async_step_init()

        items = self._data.get("customdays", [])
        return self.async_show_form(
            step_id="custom",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_build_custom_actions(), mode="list"
                        )
                    ),
                }
            ),
            description_placeholders={
                "list": _format_custom_list(items),
                "count": str(len(items)),
            },
        )

    async def async_step_custom_add(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """添加自定义节假日"""
        errors: Dict[str, str] = {}

        if user_input is not None:
            name = (user_input.get("name") or "").strip()
            date_val = user_input.get("date")
            date_str = date_val if isinstance(date_val, str) else (date_val.isoformat() if date_val else "")
            end_val = user_input.get("end") or ""
            end_str = end_val if isinstance(end_val, str) else (end_val.isoformat() if end_val else "")
            if not name or not date_str:
                errors["base"] = "missing_required"
            else:
                entry: Dict[str, str] = {
                    "name": name,
                    "uid": str(uuid.uuid4())[:8],
                }
                if end_str and end_str != date_str:
                    entry["start"] = date_str
                    entry["end"] = end_str
                else:
                    entry["date"] = date_str
                self._data.setdefault("customdays", []).append(entry)
                if await self._save_data(self._data):
                    return await self.async_step_custom()
                errors["base"] = "save_failed"

        return self.async_show_form(
            step_id="custom_add",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default="新自定义假期"): selector.TextSelector(),
                    vol.Required("date"): selector.DateSelector(),
                    vol.Optional("end", default=""): selector.DateSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_custom_delete(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """删除自定义节假日"""
        items = self._data.get("customdays", [])
        if not items:
            return await self.async_step_custom()

        if user_input is not None:
            uid = user_input.get("uid")
            for i, item in enumerate(items):
                if item.get("uid") == uid:
                    items.pop(i)
                    break
            if await self._save_data(self._data):
                return await self.async_step_custom()

        options = [
            selector.SelectOptionDict(
                value=item.get("uid", ""),
                label=f"{item.get('name', '?')} ({item.get('date', item.get('start', '?'))})",
            )
            for item in items
        ]
        return self.async_show_form(
            step_id="custom_delete",
            data_schema=vol.Schema(
                {
                    vol.Required("uid"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, mode="dropdown")
                    ),
                }
            ),
        )

    async def async_step_custom_clear(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """清空自定义节假日（带确认）"""
        if user_input is not None:
            if user_input.get("confirm") == "confirm":
                self._data["customdays"] = []
                await self._save_data(self._data)
            return await self.async_step_custom()

        return self.async_show_form(
            step_id="custom_clear",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default="cancel"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_build_confirm_options(default="cancel"), mode="list"
                        )
                    ),
                }
            ),
            description_placeholders={
                "warning": f"⚠️ 即将清空 {len(self._data.get('customdays', []))} 条自定义节假日，此操作不可撤销。",
            },
        )

    # ---------- 假期模式设置 ----------

    async def async_step_mode(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """选择假期模式"""
        if user_input is not None:
            mode_value = user_input.get("holiday_mode", HolidayMode.STANDARD.value)
            self._update_entry_mode(mode_value)
            return self.async_create_entry(title="", data={})

        current_mode = self.config_entry.data.get(
            "holiday_mode", HolidayMode.STANDARD.value
        )
        return self.async_show_form(
            step_id="mode",
            data_schema=vol.Schema(
                {
                    vol.Required("holiday_mode", default=current_mode): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_build_mode_options(), mode="list"
                        )
                    ),
                }
            ),
        )

    # ---------- 高级：JSON 编辑（兜底） ----------

    @override
    async def async_step_advanced(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """高级：直接编辑 JSON 数据"""
        errors: Dict[str, str] = {}

        current_json = "{}"
        try:
            if self._data:
                current_json = json.dumps(
                    self._data, ensure_ascii=False, indent=2
                )
        except Exception as e:
            _LOGGER.error("序列化数据失败: %s", e)
            current_json = "{}"

        if user_input is not None:
            json_content = (user_input.get("json_content") or "").strip()
            if not json_content:
                errors["json_content"] = "empty_content"
            else:
                try:
                    parsed = json.loads(json_content)
                    if not isinstance(parsed, dict):
                        errors["json_content"] = "invalid_json_structure"
                    else:
                        parsed.setdefault("holidays", [])
                        parsed.setdefault("customdays", [])
                        parsed.setdefault("studentdays", [])
                        for key in ("holidays", "customdays", "studentdays"):
                            if not isinstance(parsed[key], list):
                                errors["json_content"] = "invalid_json_structure"
                                break

                        if not errors:
                            if await self._save_data(parsed):
                                return self.async_create_entry(title="", data={})
                            else:
                                errors["json_content"] = "save_failed"

                except json.JSONDecodeError as e:
                    _LOGGER.error("JSON 解析错误: %s", e)
                    errors["json_content"] = "invalid_json"

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    vol.Required("json_content", default=current_json): selector.TemplateSelector(),
                }
            ),
            errors=errors,
            description_placeholders={
                "tips": "数据存储在 HA 的 `.storage/` 目录（JSON 格式），编辑后自动保存。",
            },
        )
