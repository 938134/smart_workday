"""Binary Sensor platform for Smart Workday - 3 个独立 boolean 实体.

is_workday       : 是否工作日（含调休上班）
is_holiday       : 是否节假日（含法定/自定义）
is_student_holiday: 是否学生假期

详细信息（日期、星期、模式、是否双休、是否调休、事件列表、未来事件）
统一挂在 is_workday 实体的属性里，其他两个实体保持纯粹。
"""

import logging
from typing import Any, Dict

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ATTR_IS_WORKDAY,
    ATTR_IS_HOLIDAY,
    ATTR_IS_WEEKEND,
    ATTR_IS_SPECIAL_WORKDAY,
    ATTR_IS_STUDENT_HOLIDAY,
    BINARY_SENSOR_TYPES,
)
from .coordinator import SmartWorkdayCoordinator

_LOGGER = logging.getLogger(__name__)


class SmartWorkdayBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """独立 boolean 二进制传感器

    - is_workday 实体承载详细信息属性（info=True）
    - is_holiday / is_student_holiday 保持纯粹（只有 on/off）
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartWorkdayCoordinator, sensor_type: str,
                 name: str, device_info: DeviceInfo, config: Dict[str, Any]):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_{sensor_type}"
        self._attr_name = name
        self._attr_icon = config["icon"]
        self._attr_device_info = device_info
        self._attr_should_poll = False
        if config.get("device_class"):
            self._attr_device_class = config["device_class"]
        self._sensor_type = sensor_type
        self._is_info_entity = bool(config.get("info"))

    @property
    def is_on(self) -> bool:
        """返回该 boolean 标志"""
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get(self._sensor_type, False)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """详细信息仅挂在 is_workday 实体上"""
        if not self._is_info_entity or not self.coordinator.data:
            return {}

        data = self.coordinator.data
        return {
            # 日期与星期
            "date": data.get("date", ""),
            "weekday": data.get("weekday_name", ""),
            # 假期模式
            "mode": data.get("mode_name", ""),
            # 布尔标志（自动化用）
            ATTR_IS_WORKDAY: data.get(ATTR_IS_WORKDAY, False),
            ATTR_IS_HOLIDAY: data.get(ATTR_IS_HOLIDAY, False),
            ATTR_IS_WEEKEND: data.get(ATTR_IS_WEEKEND, False),
            ATTR_IS_SPECIAL_WORKDAY: data.get(ATTR_IS_SPECIAL_WORKDAY, False),
            ATTR_IS_STUDENT_HOLIDAY: data.get(ATTR_IS_STUDENT_HOLIDAY, False),
            # 今日事件
            "holiday_name": data.get("primary_event", ""),
            "events": data.get("event_names", []),
            # 未来事件
            "upcoming": data.get("upcoming", []),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置 3 个 boolean 二进制传感器"""
    _LOGGER.debug("设置二进制传感器: %s", entry.entry_id)

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get("name", "智能工作日"),
        manufacturer="Smart Workday",
        model="工作日传感器",
        sw_version="2.5.0",
    )

    entities = [
        SmartWorkdayBinarySensor(coordinator, sensor_type, config["name"], device_info, config)
        for sensor_type, config in BINARY_SENSOR_TYPES.items()
    ]
    async_add_entities(entities)
    _LOGGER.info("已添加 %d 个二进制传感器", len(entities))
