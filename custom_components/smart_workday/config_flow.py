"""Config flow for Smart Workday."""

import json
import logging
from typing import Any, Dict, List, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.storage import Store

from .const import DOMAIN, DEFAULT_NAME, HolidayMode
from .coordinator import STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class SmartWorkdayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """配置流 - 处理首次添加集成"""

    VERSION = 1

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
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

        mode_options = [
            selector.SelectOptionDict(
                value=mode.value,
                label=f"{mode.icon} {mode.display_name} - {mode.description}",
            )
            for mode in HolidayMode
        ]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=DEFAULT_NAME): selector.TextSelector(),
                    vol.Required(
                        "holiday_mode", default=HolidayMode.STANDARD.value
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=mode_options, mode="dropdown"
                        )
                    ),
                }
            ),
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """获取选项流"""
        return SmartWorkdayOptionsFlow(config_entry)


class SmartWorkdayOptionsFlow(config_entries.OptionsFlow):
    """选项流 - 主菜单 + 高级 JSON 编辑"""

    def __init__(self, config_entry):
        self._config_entry = config_entry
        self._data: Dict[str, List] = {}
        self._pending_mode: str = ""

    def _get_store(self) -> Store:
        """获取当前条目的 Store 实例"""
        return Store(
            self.hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{self._config_entry.entry_id}",
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

    async def _reload_integration(self, mode_value: str):
        """更新模式并重载集成"""
        new_data = dict(self._config_entry.data)
        new_data["holiday_mode"] = mode_value
        self.hass.config_entries.async_update_entry(
            self._config_entry, data=new_data
        )
        await self.hass.config_entries.async_reload(self._config_entry.entry_id)

    # ---------- 主菜单 ----------

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None):
        """主菜单：选模式 + 选操作"""
        if not self._data:
            self._data = await self._load_data()

        if user_input is not None:
            mode_value = user_input.get(
                "holiday_mode", HolidayMode.STANDARD.value
            )
            action = user_input.get("action", "save_only")
            self._pending_mode = mode_value

            if action == "advanced":
                return await self.async_step_advanced()
            else:
                await self._reload_integration(mode_value)
                return self.async_create_entry(title="", data={})

        current_mode = self._config_entry.data.get(
            "holiday_mode", HolidayMode.STANDARD.value
        )
        stats = self._build_stats_text()

        mode_options = [
            selector.SelectOptionDict(
                value=mode.value,
                label=f"{mode.icon} {mode.display_name} - {mode.description}",
            )
            for mode in HolidayMode
        ]

        action_options = [
            selector.SelectOptionDict(value="save_only", label="💾 保存模式"),
            selector.SelectOptionDict(value="advanced", label="⚙️ 高级：直接编辑数据"),
        ]

        schema = vol.Schema(
            {
                vol.Required(
                    "holiday_mode", default=current_mode
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=mode_options, mode="dropdown")
                ),
                vol.Required("action", default="save_only"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=action_options, mode="list")
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors={},
            description_placeholders={"stats": stats},
        )

    def _build_stats_text(self) -> str:
        """构建当前假期统计文本"""
        h_count = len(self._data.get("holidays", []))
        c_count = len(self._data.get("customdays", []))
        s_count = len(self._data.get("studentdays", []))
        return (
            f"📅 **日常增删请用日历面板**（点击日期添加 / 点事件删除）\n"
            f"  • 先在 Lovelace 的「假期类型」下拉里选好类型，再去日历点击添加\n"
            f"  • 类型选项：自定义 / 法定（含调休）/ 学生\n"
            f"📦 **当前统计**：法定 {h_count} / 自定义 {c_count} / 学生 {s_count}"
        )

    # ---------- 高级：JSON 编辑 ----------

    async def async_step_advanced(
        self, user_input: Optional[Dict[str, Any]] = None
    ):
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
                                mode_value = user_input.get(
                                    "holiday_mode",
                                    self._config_entry.data.get(
                                        "holiday_mode",
                                        HolidayMode.STANDARD.value,
                                    ),
                                )
                                await self._reload_integration(mode_value)
                                return self.async_create_entry(title="", data={})
                            else:
                                errors["json_content"] = "save_failed"

                except json.JSONDecodeError as e:
                    _LOGGER.error("JSON 解析错误: %s", e)
                    errors["json_content"] = "invalid_json"

        mode_options = [
            selector.SelectOptionDict(
                value=mode.value,
                label=f"{mode.icon} {mode.display_name} - {mode.description}",
            )
            for mode in HolidayMode
        ]

        current_mode = self._config_entry.data.get(
            "holiday_mode", HolidayMode.STANDARD.value
        )

        schema = vol.Schema(
            {
                vol.Required(
                    "holiday_mode", default=current_mode
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=mode_options, mode="dropdown")
                ),
                vol.Required("json_content", default=current_json): selector.TemplateSelector(),
            }
        )

        return self.async_show_form(
            step_id="advanced",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "tips": "数据存储在 HA 的 `.storage/` 目录（JSON 格式），编辑后自动保存。",
            },
        )