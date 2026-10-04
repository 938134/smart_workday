"""Smart Workday integration."""

import logging
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    DOMAIN_DISPLAY_NAME,
    STORAGE_VERSION,
    DEFAULT_LEGAL_YEAR,
    CONF_ENABLED_LEGAL,
    LEGAL_HOLIDAY_PRESETS,
    empty_calendar_data,
)
from .coordinator import (
    SmartWorkdayDataManager, SmartWorkdayCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR]


async def _auto_import_legal_if_empty(hass: HomeAssistant, store: Store, entry: ConfigEntry):
    """启用法定假期开关且当前节假日数据为空时，自动从国务院通知预置数据导入

    - 只在节假日列表为空时导入（避免覆盖用户手工维护的数据）
    - 使用 DEFAULT_LEGAL_YEAR（根据当前年份自动计算）
    - 每次重新加载集成都会检查，因此用户清空后重新启用会重新导入
    """
    try:
        data = await store.async_load()
        if not data:
            data = empty_calendar_data()
        if data["holidays"]:
            return  # 已有数据，不覆盖

        import_year = DEFAULT_LEGAL_YEAR
        presets = LEGAL_HOLIDAY_PRESETS.get(import_year, [])
        if not presets:
            return

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

    # 创建 Store（JSON 持久化，存放在 .storage/ 目录）
    store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")

    # 自动导入法定假期：启用 legal 且当前无节假日数据时，自动从国务院通知预置数据导入
    if entry.data[CONF_ENABLED_LEGAL]:
        await _auto_import_legal_if_empty(hass, store, entry)

    # 初始化数据管理器
    data_manager = SmartWorkdayDataManager(hass, store)
    data_manager.update_enabled_flags(entry.data)

    # 初始化协调器
    coordinator = SmartWorkdayCoordinator(hass, entry.entry_id, data_manager)
    await coordinator.async_config_entry_first_refresh()

    # 存储数据
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "config": entry.data,
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
