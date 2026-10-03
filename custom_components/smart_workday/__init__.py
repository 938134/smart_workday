"""Smart Workday integration."""

import logging
import os
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    DOMAIN_DISPLAY_NAME,
    STORAGE_VERSION,
    DEFAULT_LEGAL_YEAR,
    CONF_ENABLED_LEGAL, CONF_ENABLED_STUDENT, CONF_ENABLED_CUSTOM,
    LEGAL_HOLIDAY_PRESETS,
)
from .coordinator import (
    SmartWorkdayDataManager, SmartWorkdayCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR]


async def _migrate_yaml_to_store(hass: HomeAssistant, store: Store, entry: ConfigEntry):
    """首次加载时，如果 Store 为空但存在旧版 calendar.yaml，自动迁移"""
    try:
        data = await store.async_load()
        if data is not None and isinstance(data, dict) and (
            data.get("holidays") or data.get("customdays") or data.get("studentdays")
        ):
            return  # Store 已有数据，无需迁移

        calendar_file = entry.data.get("calendar_file", "calendar.yaml")
        calendar_path = hass.config.path("custom_components", DOMAIN, calendar_file)

        if not os.path.exists(calendar_path):
            return  # 无旧文件，跳过

        import yaml
        def _read_yaml():
            with open(calendar_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        old_data = await hass.async_add_executor_job(_read_yaml)

        old_data.setdefault("holidays", [])
        old_data.setdefault("customdays", [])
        old_data.setdefault("studentdays", [])

        await store.async_save(old_data)
        _LOGGER.info("已从 calendar.yaml 迁移数据到 Store")

    except Exception as e:
        _LOGGER.error("迁移 YAML 数据失败: %s", e)


async def _auto_import_legal_if_empty(hass: HomeAssistant, store: Store, entry: ConfigEntry):
    """启用法定假期开关且当前节假日数据为空时，自动从国务院通知预置数据导入

    - 只在节假日列表为空时导入（避免覆盖用户手工维护的数据）
    - 使用 DEFAULT_LEGAL_YEAR（根据当前年份自动计算）
    - 每次重新加载集成都会检查，因此用户清空后重新启用会重新导入
    """
    try:
        data = await store.async_load()
        if not isinstance(data, dict):
            data = {}
        if data.get("holidays"):
            return  # 已有数据，不覆盖

        import_year = DEFAULT_LEGAL_YEAR
        presets = LEGAL_HOLIDAY_PRESETS.get(import_year, [])
        if not presets:
            return

        import uuid
        data.setdefault("holidays", [])
        data.setdefault("customdays", [])
        data.setdefault("studentdays", [])
        data["holidays"] = [
            {"name": item["name"], "date": item["date"], "uid": str(uuid.uuid4())[:8]}
            for item in presets
        ]
        await store.async_save(data)
        _LOGGER.info("已自动导入 %d 条 %d 年国务院法定假期", len(presets), import_year)

    except Exception as e:
        _LOGGER.error("自动导入法定假期失败: %s", e)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """设置配置条目"""
    _LOGGER.debug("设置 %s: %s", DOMAIN_DISPLAY_NAME, entry.entry_id)

    # 确保顶层开关存在（向后兼容：旧版 entry.data 缺字段默认全部启用）
    new_data = dict(entry.data)
    changed = False
    for key in (CONF_ENABLED_LEGAL, CONF_ENABLED_STUDENT, CONF_ENABLED_CUSTOM):
        if key not in new_data:
            new_data[key] = True
            changed = True
    if changed:
        hass.config_entries.async_update_entry(entry, data=new_data)

    # 创建 Store（JSON 持久化，存放在 .storage/ 目录）
    store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")

    # 迁移旧版 YAML 数据（仅首次）
    await _migrate_yaml_to_store(hass, store, entry)

    # 自动导入法定假期：启用 legal 且当前无节假日数据时，自动从国务院通知预置数据导入
    if new_data.get(CONF_ENABLED_LEGAL, True):
        await _auto_import_legal_if_empty(hass, store, entry)

    # 初始化数据管理器
    data_manager = SmartWorkdayDataManager(hass, store)
    data_manager.update_enabled_flags(new_data)

    # 初始化协调器
    coordinator = SmartWorkdayCoordinator(hass, entry.entry_id, data_manager)
    await coordinator.async_config_entry_first_refresh()

    # 存储数据
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "config": new_data,
        "coordinator": coordinator,
        "data_manager": data_manager,
        "store": store,
    }

    # 设置平台
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置条目"""
    _LOGGER.debug("卸载 %s: %s", DOMAIN_DISPLAY_NAME, entry.entry_id)

    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True

    return False