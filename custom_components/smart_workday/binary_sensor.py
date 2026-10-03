"""Binary Sensor platform for Smart Workday - 4 个布尔传感器.

v2.15.0 起，用 4 个 binary_sensor 替代旧的单个 sensor：
- is_workday:        是工作日（True/False，on/off）
- is_holiday:        是法定假期（True/False，on/off）
- is_student_holiday: 是学生假期（True/False，on/off）
- is_custom_holiday:  是自定义假期（True/False，on/off）

每个 binary_sensor 的 extra_state_attributes 保留富信息
（date, weekday, day_type, events, upcoming, 所有 is_* 标志），
方便在 Dashboard 卡片上展示详细信息。
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
    VERSION,
    DEFAULT_NAME,
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
from .coordinator import SmartWorkdayCoordinator

_LOGGER = logging.getLogger(__name__)


class SmartWorkdayBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """通用工作日/假期布尔传感器。

    通过 sensor_key 参数指定是哪个布尔标志，共用富信息 attributes。
    state 为 on/off（HA 自动从 is_on 布尔值转换）。
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: SmartWorkdayCoordinator,
        device_info: DeviceInfo,
        sensor_key: str,
        entity_name: str,
        icon: str,
        unique_suffix: str,
    ):
        super().__init__(coordinator)
        self._sensor_key = sensor_key
        self._attr_unique_id = f"{coordinator.entry_id}_{unique_suffix}"
        self._attr_name = entity_name
        self._attr_device_info = device_info
        self._attr_sw_version = VERSION
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        """返回布尔值：True 表示该标志为真（on），False 表示为假（off）"""
        data = self.coordinator.data
        if not data:
            return False
        return bool(data.get(self._sensor_key, False))

    @property
    def available(self) -> bool:
        """显式返回 True，避免 coordinator 更新失败时实体显示不可用"""
        return True

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """所有详细信息挂在 attributes 里（富信息）"""
        data = self.coordinator.data
        if not data:
            return {}

        return {
            # 主要类型（优先级：调休上班 > 法定假期 > 周末 > 工作日）
            ATTR_DAY_TYPE: data.get(ATTR_DAY_TYPE, ""),
            # 日期与星期
            "date": data.get("date", ""),
            "weekday": data.get("weekday_name", ""),
            # 布尔标志（所有标志都挂上，方便自动化引用）
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
    """设置 4 个布尔传感器实体"""
    _LOGGER.debug("设置布尔传感器: %s", entry.entry_id)

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get("name", DEFAULT_NAME),
        manufacturer=DOMAIN_DISPLAY_NAME,
        model=BINARY_SENSOR_MODEL,
        sw_version=VERSION,
    )

    # 4 个布尔传感器（名称、icon、unique_suffix、对应的 data 键）
    sensors = [
        SmartWorkdayBinarySensor(
            coordinator, device_info,
            sensor_key=ATTR_IS_WORKDAY,
            entity_name=BINARY_SENSOR_IS_WORKDAY,
            icon="mdi:briefcase-check",
            unique_suffix="is_workday",
        ),
        SmartWorkdayBinarySensor(
            coordinator, device_info,
            sensor_key=ATTR_IS_HOLIDAY,
            entity_name=BINARY_SENSOR_IS_HOLIDAY,
            icon="mdi:calendar-check",
            unique_suffix="is_holiday",
        ),
        SmartWorkdayBinarySensor(
            coordinator, device_info,
            sensor_key=ATTR_IS_STUDENT_HOLIDAY,
            entity_name=BINARY_SENSOR_IS_STUDENT_HOLIDAY,
            icon="mdi:school",
            unique_suffix="is_student_holiday",
        ),
        SmartWorkdayBinarySensor(
            coordinator, device_info,
            sensor_key=ATTR_IS_CUSTOM_HOLIDAY,
            entity_name=BINARY_SENSOR_IS_CUSTOM_HOLIDAY,
            icon="mdi:star",
            unique_suffix="is_custom_holiday",
        ),
    ]

    async_add_entities(sensors)
    _LOGGER.info("已添加 %d 个布尔传感器实体", len(sensors))
