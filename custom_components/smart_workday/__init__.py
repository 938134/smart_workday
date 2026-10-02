"""Smart Workday integration."""

import logging
import os
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN, HolidayMode,
    CONF_ENABLED_LEGAL, CONF_ENABLED_STUDENT, CONF_ENABLED_CUSTOM,
)
from .coordinator import (
    SmartWorkdayDataManager, SmartWorkdayCoordinator,
    STORAGE_VERSION,
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """设置配置条目"""
    _LOGGER.debug("设置 Smart Workday: %s", entry.entry_id)

    # 确保模式和顶层开关存在（向后兼容：旧版 entry.data 缺字段默认全部启用）
    new_data = dict(entry.data)
    changed = False
    if "holiday_mode" not in new_data:
        new_data["holiday_mode"] = HolidayMode.STANDARD.value
        changed = True
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

    # 初始化数据管理器
    data_manager = SmartWorkdayDataManager(hass, store)
    data_manager.update_holiday_mode(
        HolidayMode(new_data.get("holiday_mode", HolidayMode.STANDARD.value))
    )
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
    _LOGGER.debug("卸载 Smart Workday: %s", entry.entry_id)

    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True

    return False