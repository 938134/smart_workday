"""Binary Sensor platform for Smart Workday - 4 个布尔传感器.

v2.15.0 起，用 4 个 binary_sensor 替代旧的单个 sensor：
- is_workday:        工作日（True/False，on/off）
- is_holiday:        法定假期（True/False，on/off）
- is_student_holiday: 学生假期（True/False，on/off）
- is_custom_holiday:  自定义假期（True/False，on/off）

每个 binary_sensor 的 extra_state_attributes 保留富信息
（date, weekday, day_type, events, upcoming, 所有 is_* 标志），
方便在 Dashboard 卡片上展示详细信息。

v2.18.0：改用 coordinator.data["day_info"] 对象直接访问，SENSOR_DEFS 数据驱动。

v2.19.0：清理冗余 —— 删除从未读取的 sensor_key 列、_attr_should_poll
    （CoordinatorEntity 默认 False）、_attr_sw_version（DeviceInfo 已带，实体级被忽略）。

v2.20.1：删除 available / write_ha_state 覆盖。coordinator.load_calendar_data
    已用 setdefault 兜底补齐 Store 缺失字段，_async_update_data 不会再因
    Store 结构问题抛 UpdateFailed，实体层不再需要强制 available=True。
    实体可用性回归 HA 标准行为（跟随 coordinator.last_update_success），
    用户/自动化也可通过 HA 工具正常设置状态。
"""

import logging
from typing import Any, Dict, List, Tuple

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, RestoreEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    VERSION,
    DOMAIN_DISPLAY_NAME,
    BINARY_SENSOR_MODEL,
    BINARY_SENSOR_IS_WORKDAY,
    BINARY_SENSOR_IS_HOLIDAY,
    BINARY_SENSOR_IS_STUDENT_HOLIDAY,
    BINARY_SENSOR_IS_CUSTOM_HOLIDAY,
    ATTR_IS_WORKDAY,
    ATTR_IS_HOLIDAY,
    ATTR_IS_WEEKEND,
    ATTR_IS_SPECIAL_WORKDAY,
    ATTR_IS_STUDENT_HOLIDAY,
    ATTR_IS_CUSTOM_HOLIDAY,
    ATTR_DAY_TYPE,
)
from .coordinator import SmartWorkdayCoordinator, DayInfo

_LOGGER = logging.getLogger(__name__)

# (entity_name, icon, unique_suffix, DayInfo 属性名)
SENSOR_DEFS: List[Tuple[str, str, str, str]] = [
    (BINARY_SENSOR_IS_WORKDAY, "mdi:briefcase-check", "is_workday", "is_workday"),
    (BINARY_SENSOR_IS_HOLIDAY, "mdi:calendar-check", "is_holiday", "is_holiday"),
    (BINARY_SENSOR_IS_STUDENT_HOLIDAY, "mdi:school", "is_student_holiday", "is_student_holiday"),
    (BINARY_SENSOR_IS_CUSTOM_HOLIDAY, "mdi:star", "is_custom_holiday", "is_custom_holiday"),
]


class SmartWorkdayBinarySensor(RestoreEntity, CoordinatorEntity, BinarySensorEntity):
    """通用工作日/假期布尔传感器。

    通过 day_info_attr 属性名从 coordinator.data["day_info"] 读取布尔值。
    state 为 on/off（HA 自动从 is_on 布尔值转换）。
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SmartWorkdayCoordinator,
        device_info: DeviceInfo,
        entity_name: str,
        icon: str,
        unique_suffix: str,
        day_info_attr: str,
    ):
        super().__init__(coordinator)
        self._day_info_attr = day_info_attr
        self._attr_unique_id = f"{coordinator.entry_id}_{unique_suffix}"
        self._attr_name = entity_name
        self._attr_device_info = device_info
        self._attr_icon = icon

    def _get_day_info(self) -> DayInfo | None:
        data = self.coordinator.data
        return data.get("day_info") if data else None

    @property
    def is_on(self) -> bool:
        """返回布尔值：True 表示该标志为真（on），False 表示为假（off）"""
        day_info = self._get_day_info()
        return bool(getattr(day_info, self._day_info_attr, False)) if day_info else False

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """所有详细信息挂在 attributes 里（富信息）"""
        day_info = self._get_day_info()
        if not day_info:
            return {}

        data = self.coordinator.data
        return {
            ATTR_DAY_TYPE: day_info.day_type,
            "date": day_info.date,
            "weekday": day_info.weekday_name,
            ATTR_IS_WORKDAY: day_info.is_workday,
            ATTR_IS_HOLIDAY: day_info.is_holiday,
            ATTR_IS_WEEKEND: day_info.is_weekend,
            ATTR_IS_SPECIAL_WORKDAY: day_info.is_special_workday,
            ATTR_IS_STUDENT_HOLIDAY: day_info.is_student_holiday,
            ATTR_IS_CUSTOM_HOLIDAY: day_info.is_custom_holiday,
            "holiday_name": day_info.primary_event,
            "events": day_info.event_names,
            "upcoming": data.get("upcoming", []) if data else [],
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置 4 个布尔传感器实体"""
    _LOGGER.debug("设置布尔传感器: %s", entry.entry_id)

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data["name"],
        manufacturer=DOMAIN_DISPLAY_NAME,
        model=BINARY_SENSOR_MODEL,
        sw_version=VERSION,
    )

    sensors = [
        SmartWorkdayBinarySensor(coordinator, device_info, *defn)
        for defn in SENSOR_DEFS
    ]

    async_add_entities(sensors)
    _LOGGER.info("已添加 %d 个布尔传感器实体", len(sensors))
