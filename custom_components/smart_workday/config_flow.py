"""Config flow for Smart Workday - 两步式 UI 表单。

ConfigFlow 与 OptionsFlow 使用同一套步骤逻辑（共享基类 BaseWorkdayFlow）：
- 第 1 步 (init)：名称(ConfigFlow 独有) + 假期模式 + 3 个顶层启用开关
- 第 2 步 (route)：根据开关状态自动路由到对应分类编辑页
- 各分类编辑页：法定节假日 / 学生假期 / 自定义假期
- 高级 JSON 编辑：兜底（在路由页可选）
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, override

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    DEFAULT_NAME,
    HolidayMode,
    LEGAL_HOLIDAY_PRESETS,
    STUDENT_HOLIDAY_DEFAULTS,
    StudentHolidayType,
    CONF_ENABLED_LEGAL,
    CONF_ENABLED_STUDENT,
    CONF_ENABLED_CUSTOM,
    CONF_HOLIDAY_MODE,
    CONF_NAME,
    ENABLED_LABELS,
    EVENT_SOURCE_LEGAL,
    EVENT_SOURCE_STUDENT,
    EVENT_SOURCE_CUSTOM,
    EVENT_SOURCE_MAKEUP,
    SOURCE_TO_CATEGORY,
)
from .coordinator import STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


# ============================================================
# 辅助函数：构建选项 / 格式化文本
# ============================================================

def _build_mode_options() -> List[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(
            value=mode.value,
            label=f"{mode.icon} {mode.display_name} - {mode.description}",
        )
        for mode in HolidayMode
    ]


def _build_route_actions(enabled_legal: bool, enabled_student: bool,
                          enabled_custom: bool) -> List[selector.SelectOptionDict]:
    """构建路由步骤的操作选项，只显示已启用的分类"""
    options: List[selector.SelectOptionDict] = []
    if enabled_legal:
        options.append(selector.SelectOptionDict(
            value="legal", label="📅 法定节假日"
        ))
    if enabled_student:
        options.append(selector.SelectOptionDict(
            value="student", label="🎓 学生假期"
        ))
    if enabled_custom:
        options.append(selector.SelectOptionDict(
            value="custom", label="⭐ 自定义假期"
        ))
    options.append(selector.SelectOptionDict(
        value="advanced", label="📝 高级 JSON 编辑"
    ))
    options.append(selector.SelectOptionDict(
        value="back", label="✅ 完成（返回主菜单）"
    ))
    return options


def _build_legal_actions() -> List[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(value="import", label="📥 从 2026 国务院通知导入（覆盖）"),
        selector.SelectOptionDict(value="add", label="➕ 手动添加一条"),
        selector.SelectOptionDict(value="delete", label="🗑️ 删除某条"),
        selector.SelectOptionDict(value="clear", label="⚠️ 清空全部"),
        selector.SelectOptionDict(value="back", label="⬅️ 返回上一步"),
    ]


def _build_custom_actions() -> List[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(value="add", label="➕ 添加一条"),
        selector.SelectOptionDict(value="delete", label="🗑️ 删除某条"),
        selector.SelectOptionDict(value="clear", label="⚠️ 清空全部"),
        selector.SelectOptionDict(value="back", label="⬅️ 返回上一步"),
    ]


def _build_confirm_options() -> List[selector.SelectOptionDict]:
    """确认对话框（默认选中确认）"""
    return [
        selector.SelectOptionDict(value="confirm", label="✅ 确认执行"),
        selector.SelectOptionDict(value="cancel", label="❌ 取消"),
    ]


def _build_legal_type_options() -> List[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(value="off", label="🌴 放假"),
        selector.SelectOptionDict(value="work", label="💼 调休上班"),
    ]


def _build_year_options() -> List[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(
            value=str(year), label=f"{year} 年国务院通知"
        )
        for year in sorted(LEGAL_HOLIDAY_PRESETS.keys())
    ]


def _format_legal_list(items: List[Dict]) -> str:
    if not items:
        return "_暂无法定节假日数据_\n\n💡 可用「📥 从 2026 国务院通知导入」一键填充"
    lines = []
    grouped: Dict[str, List[Dict]] = {}
    for item in items:
        name = item.get("name", "?")
        key = "调休上班日" if "调休" in name else name
        grouped.setdefault(key, []).append(item)
    for name, entries in grouped.items():
        dates = sorted([e.get("date", "") for e in entries])
        lines.append(f"• **{name}**：{', '.join(dates)}")
    return "\n".join(lines[:15]) + (f"\n\n... 共 {len(items)} 条" if len(items) > 15 else "")


def _format_custom_list(items: List[Dict]) -> str:
    if not items:
        return "_暂无自定义节假日_"
    return "\n".join([f"• {i.get('name', '?')}：{i.get('date', i.get('start', '?'))}" for i in items])


def _format_student_summary(items: List[Dict]) -> str:
    if not items:
        return "_尚未配置学生假期_"
    lines = []
    for item in items:
        enabled = item.get("enabled", True)
        status = "✅ 启用" if enabled else "❌ 禁用"
        name = item.get("name", "?")
        if "date" in item:
            lines.append(f"• {name}：{status} - {item.get('date', '未设置')}")
        else:
            lines.append(f"• {name}：{status} - {item.get('start', '未设置')} ~ {item.get('end', '未设置')}")
    return "\n".join(lines)


# ============================================================
# 共享基类：ConfigFlow 和 OptionsFlow 复用所有步骤
# ============================================================

class BaseWorkdayFlow:
    """ConfigFlow 和 OptionsFlow 共享的辅助方法基类。

    - Store 数据存取 (_load_data / _save_data / _ensure_data)
    - entry.data 开关读写 (_update_entry_flags / _get_flags)
    - async_step_route 及以下的子步骤（法定/学生/自定义编辑、高级编辑）

    ⚠️ 不共享入口步骤：HA ConfigFlow 入口是 async_step_user，
    OptionsFlow 入口才是 async_step_init，二者无法复用。
    ConfigFlow 只做「名称 + 模式 + 开关」后 create_entry，
    HA 自动跳到 OptionsFlow 的第二步继续。
    """

    async def _ensure_data(self) -> Dict[str, Any]:
        if not getattr(self, "_data_loaded", False):
            self._data = await self._load_data()
            self._data_loaded = True
        return self._data

    def _get_store(self) -> Store:
        return Store(
            self.hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{self.config_entry.entry_id}",
        )

    async def _load_data(self) -> Dict[str, Any]:
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
        try:
            store = self._get_store()
            for key in ("holidays", "customdays", "studentdays"):
                data[key].sort(key=lambda x: x.get("date") or x.get("start", ""))
            await store.async_save(data)
            self._data = data  # 缓存同步
            _LOGGER.info("数据保存成功")
            return True
        except Exception as e:
            _LOGGER.error("保存数据失败: %s", e)
            return False

    def _update_entry_flags(self, flags: Dict[str, bool]) -> None:
        """更新 entry.data 中的顶层开关和模式"""
        new_data = dict(self.config_entry.data)
        new_data.update(flags)
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=new_data
        )

    def _get_flags(self) -> Dict[str, Any]:
        """读取当前 entry.data 中的开关和模式"""
        d = self.config_entry.data
        return {
            CONF_ENABLED_LEGAL: bool(d.get(CONF_ENABLED_LEGAL, True)),
            CONF_ENABLED_STUDENT: bool(d.get(CONF_ENABLED_STUDENT, True)),
            CONF_ENABLED_CUSTOM: bool(d.get(CONF_ENABLED_CUSTOM, True)),
            CONF_HOLIDAY_MODE: d.get(CONF_HOLIDAY_MODE, HolidayMode.STANDARD.value),
        }

    # ================================================================
    # 第 2 步：route（根据启用了哪一类自动路由到编辑页）
    # ================================================================

    @override
    async def async_step_route(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """第 2 步：路由到启用的分类编辑页（或高级编辑）"""
        flags = self._get_flags()

        if user_input is not None:
            action = user_input.get("action")
            if action == "legal" and flags[CONF_ENABLED_LEGAL]:
                return await self.async_step_legal()
            elif action == "student" and flags[CONF_ENABLED_STUDENT]:
                return await self.async_step_student()
            elif action == "custom" and flags[CONF_ENABLED_CUSTOM]:
                return await self.async_step_custom()
            elif action == "advanced":
                return await self.async_step_advanced()
            elif action == "back":
                return await self.async_step_finish()

        return self.async_show_form(
            step_id="route",
            data_schema=vol.Schema({
                vol.Required("action"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_build_route_actions(
                            flags[CONF_ENABLED_LEGAL],
                            flags[CONF_ENABLED_STUDENT],
                            flags[CONF_ENABLED_CUSTOM],
                        ),
                        mode="list",
                    )
                ),
            }),
            description_placeholders={
                "stats": self._build_route_stats(),
            },
        )

    async def _build_route_stats(self) -> str:
        data = await self._ensure_data()
        h_count = len(data.get("holidays", []))
        s_count = len(data.get("studentdays", []))
        c_count = len(data.get("customdays", []))
        return (
            f"📊 **数据概览**\n"
            f"  • 📅 法定节假日：{h_count} 条\n"
            f"  • 🎓 学生假期：{s_count} 条\n"
            f"  • ⭐ 自定义假期：{c_count} 条"
        )

    # ================================================================
    # 法定节假日管理
    # ================================================================

    async def async_step_legal(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
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
                return await self.async_step_route()

        data = await self._ensure_data()
        items = data.get("holidays", [])
        return self.async_show_form(
            step_id="legal",
            data_schema=vol.Schema({
                vol.Required("action"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_build_legal_actions(), mode="list")
                ),
            }),
            description_placeholders={
                "list": _format_legal_list(items),
                "count": str(len(items)),
            },
        )

    async def async_step_legal_import(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """从预置数据导入法定节假日"""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                year = int(user_input.get("year"))
            except (ValueError, TypeError):
                year = 2026
            if user_input.get("confirm") == "confirm":
                presets = LEGAL_HOLIDAY_PRESETS.get(year, [])
                data = await self._ensure_data()
                data["holidays"] = [
                    {"name": item["name"], "date": item["date"], "uid": str(uuid.uuid4())[:8]}
                    for item in presets
                ]
                if await self._save_data(data):
                    return await self.async_step_legal()
                errors["base"] = "save_failed"
            else:
                return await self.async_step_legal()

        return self.async_show_form(
            step_id="legal_import",
            data_schema=vol.Schema({
                vol.Required("year", default="2026"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_build_year_options(), mode="dropdown")
                ),
                vol.Required("confirm", default="confirm"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_build_confirm_options(), mode="list")
                ),
            }),
            errors=errors,
            description_placeholders={
                "warning": (
                    "⚠️ 导入将覆盖当前所有法定节假日数据。\n"
                    f"支持年份：{', '.join(str(y) for y in sorted(LEGAL_HOLIDAY_PRESETS.keys()))}"
                ),
            },
        )

    async def async_step_legal_add(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
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
                # 调休上班日自动补名称
                if htype == "work" and "调休" not in name:
                    name = f"{name}调休上班"
                data = await self._ensure_data()
                data.setdefault("holidays", []).append({
                    "name": name,
                    "date": date_str,
                    "uid": str(uuid.uuid4())[:8],
                })
                if await self._save_data(data):
                    return await self.async_step_legal()
                errors["base"] = "save_failed"

        return self.async_show_form(
            step_id="legal_add",
            data_schema=vol.Schema({
                vol.Required("name", default="新假期"): selector.TextSelector(),
                vol.Required("date"): selector.DateSelector(),
                vol.Required("type", default="off"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_build_legal_type_options(), mode="list")
                ),
            }),
            errors=errors,
        )

    async def async_step_legal_delete(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """删除法定节假日条目"""
        data = await self._ensure_data()
        items = data.get("holidays", [])
        if not items:
            return await self.async_step_legal()

        if user_input is not None:
            uid = user_input.get("uid")
            for i, item in enumerate(items):
                if item.get("uid") == uid:
                    items.pop(i)
                    break
            if await self._save_data(data):
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
            data_schema=vol.Schema({
                vol.Required("uid"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode="dropdown")
                ),
            }),
        )

    async def async_step_legal_clear(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """清空法定节假日"""
        if user_input is not None:
            if user_input.get("confirm") == "confirm":
                data = await self._ensure_data()
                data["holidays"] = []
                await self._save_data(data)
            return await self.async_step_legal()

        data = await self._ensure_data()
        count = len(data.get("holidays", []))
        return self.async_show_form(
            step_id="legal_clear",
            data_schema=vol.Schema({
                vol.Required("confirm", default="confirm"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_build_confirm_options(), mode="list")
                ),
            }),
            description_placeholders={
                "warning": f"⚠️ 即将清空 {count} 条法定节假日数据，此操作不可撤销。",
            },
        )

    # ================================================================
    # 学生假期管理（一次性表单：5 项 checkbox + 日期）
    # ================================================================

    async def async_step_student(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """学生假期 - 5 项 checkbox + 日期一次性表单"""
        errors: Dict[str, str] = {}

        if user_input is not None:
            data = await self._ensure_data()
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

            data["studentdays"] = new_studentdays
            if await self._save_data(data):
                return await self.async_step_route()
            errors["base"] = "save_failed"

        data = await self._ensure_data()
        return self.async_show_form(
            step_id="student",
            data_schema=self._student_schema(data),
            errors=errors,
            description_placeholders={
                "current": _format_student_summary(data.get("studentdays", [])),
            },
        )

    def _student_schema(self, data: Dict) -> vol.Schema:
        """学生假期表单 schema"""
        current = {item.get("type"): item for item in data.get("studentdays", [])}
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

    # ================================================================
    # 自定义节假日管理
    # ================================================================

    async def async_step_custom(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
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
                return await self.async_step_route()

        data = await self._ensure_data()
        items = data.get("customdays", [])
        return self.async_show_form(
            step_id="custom",
            data_schema=vol.Schema({
                vol.Required("action"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_build_custom_actions(), mode="list")
                ),
            }),
            description_placeholders={
                "list": _format_custom_list(items),
                "count": str(len(items)),
            },
        )

    async def async_step_custom_add(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
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
                data = await self._ensure_data()
                data.setdefault("customdays", []).append(entry)
                if await self._save_data(data):
                    return await self.async_step_custom()
                errors["base"] = "save_failed"

        return self.async_show_form(
            step_id="custom_add",
            data_schema=vol.Schema({
                vol.Required("name", default="新自定义假期"): selector.TextSelector(),
                vol.Required("date"): selector.DateSelector(),
                vol.Optional("end", default=""): selector.DateSelector(),
            }),
            errors=errors,
        )

    async def async_step_custom_delete(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """删除自定义节假日"""
        data = await self._ensure_data()
        items = data.get("customdays", [])
        if not items:
            return await self.async_step_custom()

        if user_input is not None:
            uid = user_input.get("uid")
            for i, item in enumerate(items):
                if item.get("uid") == uid:
                    items.pop(i)
                    break
            if await self._save_data(data):
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
            data_schema=vol.Schema({
                vol.Required("uid"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode="dropdown")
                ),
            }),
        )

    async def async_step_custom_clear(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """清空自定义节假日"""
        if user_input is not None:
            if user_input.get("confirm") == "confirm":
                data = await self._ensure_data()
                data["customdays"] = []
                await self._save_data(data)
            return await self.async_step_custom()

        data = await self._ensure_data()
        count = len(data.get("customdays", []))
        return self.async_show_form(
            step_id="custom_clear",
            data_schema=vol.Schema({
                vol.Required("confirm", default="confirm"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_build_confirm_options(), mode="list")
                ),
            }),
            description_placeholders={
                "warning": f"⚠️ 即将清空 {count} 条自定义节假日，此操作不可撤销。",
            },
        )

    # ================================================================
    # 高级 JSON 编辑（兜底）
    # ================================================================

    @override
    async def async_step_advanced(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """高级：直接编辑 JSON 数据"""
        errors: Dict[str, str] = {}

        current_json = "{}"
        try:
            data = await self._ensure_data()
            current_json = json.dumps(data, ensure_ascii=False, indent=2)
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
                                return await self.async_step_route()
                            else:
                                errors["json_content"] = "save_failed"

                except json.JSONDecodeError as e:
                    _LOGGER.error("JSON 解析错误: %s", e)
                    errors["json_content"] = "invalid_json"

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema({
                vol.Required("json_content", default=current_json): selector.TemplateSelector(),
            }),
            errors=errors,
            description_placeholders={
                "tips": "数据存储在 HA 的 `.storage/` 目录（JSON 格式），编辑后自动保存。",
            },
        )


# ============================================================
# ConfigFlow - 首次添加集成（一步：名称 + 模式 + 开关）
# ============================================================

class SmartWorkdayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Smart Workday 配置流 - 首次添加时只填基础信息，
    HA 会自动跳到 OptionsFlow 继续详细配置。
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
        """第 1 步（也是唯一一步）：名称 + 模式 + 3 个启用开关"""
        errors: Dict[str, str] = {}

        if user_input is not None:
            name = (user_input.get(CONF_NAME) or DEFAULT_NAME).strip() or DEFAULT_NAME
            data = {
                CONF_NAME: name,
                CONF_HOLIDAY_MODE: user_input[CONF_HOLIDAY_MODE],
                CONF_ENABLED_LEGAL: bool(user_input[CONF_ENABLED_LEGAL]),
                CONF_ENABLED_STUDENT: bool(user_input[CONF_ENABLED_STUDENT]),
                CONF_ENABLED_CUSTOM: bool(user_input[CONF_ENABLED_CUSTOM]),
            }
            return self.async_create_entry(title=name, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
                vol.Required(CONF_HOLIDAY_MODE, default=HolidayMode.STANDARD.value): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_build_mode_options(), mode="dropdown")
                ),
                vol.Required(CONF_ENABLED_LEGAL, default=True): selector.BooleanSelector(),
                vol.Required(CONF_ENABLED_STUDENT, default=True): selector.BooleanSelector(),
                vol.Required(CONF_ENABLED_CUSTOM, default=True): selector.BooleanSelector(),
            }),
            errors=errors,
            description_placeholders={
                "tips": (
                    "⚙️ 输入集成名称、选择模式、勾选启用的假期类型。\n"
                    "💡 提交后会跳到第 2 步继续详细配置。"
                ),
            },
        )


# ============================================================
# OptionsFlow - 修改配置（两步：开关 + 路由编辑）
# ============================================================

class SmartWorkdayOptionsFlow(BaseWorkdayFlow, OptionsFlowWithReload):
    """Smart Workday 选项流 - 两步式 UI 表单

    - 第 1 步 (init)：3 个启用开关 + 假期模式
    - 第 2 步 (route)：根据启用了哪一类路由到编辑页

    继承 OptionsFlowWithReload：async_create_entry 自动 reload entry。
    ⚠️ 不要覆盖 __init__：HA 会自动注入 self.config_entry。
    """

    @override
    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> ConfigFlowResult:
        """第 1 步：模式 + 3 个启用开关"""
        if user_input is not None:
            # 保存开关到 entry.data
            flags = {
                CONF_ENABLED_LEGAL: bool(user_input[CONF_ENABLED_LEGAL]),
                CONF_ENABLED_STUDENT: bool(user_input[CONF_ENABLED_STUDENT]),
                CONF_ENABLED_CUSTOM: bool(user_input[CONF_ENABLED_CUSTOM]),
                CONF_HOLIDAY_MODE: user_input[CONF_HOLIDAY_MODE],
            }
            self._update_entry_flags(flags)
            # 自动进入第 2 步
            return await self.async_step_route()

        current = self._get_flags()
        schema = vol.Schema({
            vol.Required(CONF_HOLIDAY_MODE, default=current[CONF_HOLIDAY_MODE]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=_build_mode_options(), mode="dropdown")
            ),
            vol.Required(CONF_ENABLED_LEGAL, default=current[CONF_ENABLED_LEGAL]): selector.BooleanSelector(),
            vol.Required(CONF_ENABLED_STUDENT, default=current[CONF_ENABLED_STUDENT]): selector.BooleanSelector(),
            vol.Required(CONF_ENABLED_CUSTOM, default=current[CONF_ENABLED_CUSTOM]): selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"tips": self._build_init_tips(current)},
        )

    def _build_init_tips(self, flags: Dict[str, Any]) -> str:
        mode_obj = next(
            (m for m in HolidayMode if m.value == flags[CONF_HOLIDAY_MODE]),
            HolidayMode.STANDARD,
        )
        return (
            f"⚙️ **当前配置**\n"
            f"  • 模式：{mode_obj.display_name}\n"
            f"  • 📅 法定节假日：{'✅ 启用' if flags[CONF_ENABLED_LEGAL] else '❌ 禁用'}\n"
            f"  • 🎓 学生假期：{'✅ 启用' if flags[CONF_ENABLED_STUDENT] else '❌ 禁用'}\n"
            f"  • ⭐ 自定义假期：{'✅ 启用' if flags[CONF_ENABLED_CUSTOM] else '❌ 禁用'}\n"
            f"\n💡 禁用某类假期后，该类数据不再显示也不参与工作日/节假日判定。"
        )

    @override
    async def async_step_finish(self) -> ConfigFlowResult:
        """完成选项流（HA 会自动 reload）"""
        return self.async_create_entry(title="", data={})
