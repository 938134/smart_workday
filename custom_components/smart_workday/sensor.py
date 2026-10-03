"""Sensor platform for Smart Workday - 单个传感器实体.

state = "工作日" 或 "非工作日"
详细信息（日期、星期、day_type、所有布尔标志、事件列表、未来事件）
统一挂在 attributes 里。

学生假期 / 自定义假期作为独立标志位，不影响工作日判定，
仅在 attributes 中标记，并在日历上显示。
"""

import logging
from typing import Any, Dict

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    VERSION,
    DEFAULT_NAME,
    DOMAIN_DISPLAY_NAME,
    SENSOR_MODEL,
    SENSOR_ENTITY_NAME,
    SENSOR_STATUS_WORKDAY,
    SENSOR_STATUS_NON_WORKDAY,
    ATTR_IS_WORKDAY,
    ATTR_IS_HOLIDAY,
    ATTR_IS_WEEKEND,
    ATTR_IS_SPECIAL_WORKDAY,
    ATTR_IS_STUDENT_HOLIDAY,
    ATTR_IS_CUSTOM_HOLIDAY,
    ATTR_DAY_TYPE,
)
from .coordinator import SmartWorkdayCoordinator

_LOGGER = logging.getLogger(__name__)


class SmartWorkdaySensor(CoordinatorEntity, SensorEntity):
    """单个工作日状态传感器.

    state: "工作日" / "非工作日"
    attributes: day_type, is_workday, is_holiday, is_weekend, is_special_workday,
                is_student_holiday, is_custom_holiday, date, weekday,
                holiday_name, events, upcoming
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_native_unit_of_measurement = None
    _attr_icon = "mdi:briefcase-check"
    _attr_name = SENSOR_ENTITY_NAME

    def __init__(self, coordinator: SmartWorkdayCoordinator, device_info: DeviceInfo):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_sensor"
        self._attr_device_info = device_info
        self._attr_sw_version = VERSION

    @property
    def native_value(self) -> str:
        """返回状态：工作日 / 非工作日（永不返回 None，避免 HA 显示不可用）"""
        data = self.coordinator.data
        if not data:
            return SENSOR_STATUS_NON_WORKDAY  # 数据未加载时默认视为非工作日
        return SENSOR_STATUS_WORKDAY if data.get(ATTR_IS_WORKDAY) else SENSOR_STATUS_NON_WORKDAY

    @property
    def available(self) -> bool:
        """显式返回 True，避免 HA 因 native_value 边界显示不可用"""
        return True

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """所有详细信息挂在 attributes 里"""
        data = self.coordinator.data
        if not data:
            return {}

        return {
            # 主要类型（优先级：调休上班 > 法定假期 > 周末 > 工作日）
            ATTR_DAY_TYPE: data.get(ATTR_DAY_TYPE, ""),
            # 日期与星期
            "date": data.get("date", ""),
            "weekday": data.get("weekday_name", ""),
            # 布尔标志（自动化用）
            ATTR_IS_WORKDAY: data.get(ATTR_IS_WORKDAY, False),
            ATTR_IS_HOLIDAY: data.get(ATTR_IS_HOLIDAY, False),
            ATTR_IS_WEEKEND: data.get(ATTR_IS_WEEKEND, False),
            ATTR_IS_SPECIAL_WORKDAY: data.get(ATTR_IS_SPECIAL_WORKDAY, False),
            ATTR_IS_STUDENT_HOLIDAY: data.get(ATTR_IS_STUDENT_HOLIDAY, False),
            ATTR_IS_CUSTOM_HOLIDAY: data.get(ATTR_IS_CUSTOM_HOLIDAY, False),
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
    """设置单个工作日状态传感器"""
    _LOGGER.debug("设置传感器: %s", entry.entry_id)

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get("name", DEFAULT_NAME),
        manufacturer=DOMAIN_DISPLAY_NAME,
        model=SENSOR_MODEL,
        sw_version=VERSION,
    )

    async_add_entities([SmartWorkdaySensor(coordinator, device_info)])
    _LOGGER.info("已添加 %s 实体", SENSOR_ENTITY_NAME)
