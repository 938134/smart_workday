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

v2.19.0：显式覆盖 `available` property 返回 True，与 calendar 一致。
    防止 coordinator.last_update_success 抖动（例如 _async_update_data
    因 Store 缺字段抛 UpdateFailed）导致所有 sensor 集体变 unavailable。
    同时清理冗余：删除从未读取的 sensor_key 列、_attr_should_poll（CoordinatorEntity
    默认 False）、_attr_sw_version（DeviceInfo 已带，实体级被忽略）。
"""

import logging
from typing import Any, Dict, List, Tuple

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
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


class SmartWorkdayBinarySensor(CoordinatorEntity, BinarySensorEntity):
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

    @property
    def available(self) -> bool:
        """显式返回 True：即便 coordinator 刷新失败，sensor 也不变 unavailable。

        与 calendar 的 available 覆盖保持一致。
        _get_day_info 里已经做了兜底：day_info 缺失时 is_on 返回 False，
        所以即使 last_update_success=False，sensor 仍可读到一个合理的状态。
        同步 _attr_available=True 防止 HA write_ha_state 读到 False 就把 state 覆盖为 None。
        """
        self._attr_available = True
        return True

    def write_ha_state(self, *args, **kwargs) -> None:
        """覆盖 HA 的 write_ha_state，强制 _attr_available 为 True。

        HA 2026.5+ 中 write_ha_state 直接读 _attr_available（不走 available property），
        若为 False 会把 state 强制设为 None（Logbook 记为 unavailable）。
        CoordinatorEntity 的 last_update_success 抖动会通过 MRO 间接污染 _attr_available，
        所以每次写状态前强制重置为 True。与 calendar.write_ha_state 保持一致。
        """
        self._attr_available = True
        super().write_ha_state(*args, **kwargs)

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
