"""Binary Sensor platform for Smart Workday - 3 常规 + 2 诊断 布尔传感器.

v3.1.0：新增 2 个诊断传感器（数据源健康检查，on/off）
- 法定假期诊断：legal 数据非空 = on，详情挂 attributes（今天状态/下一个假期/距今天数）
- 自定义假期诊断：custom 数据非空 = on，详情挂 attributes（今天活跃类别）
- 常规 3 个：is_workday / is_holiday / is_custom_holiday

v3.0.0 破坏性重构：
- 4 → 3 个 sensor：删除 is_student_holiday（学生假期实质是自定义假期的一个类别）
- 保留：is_workday / is_holiday / is_custom_holiday
- 学生/工作/个人/家庭 等具体类别通过 attributes.active_custom 精确暴露
  例如 attributes.active_custom = {"学生": ["寒假"], "工作": ["出差"]}
"""

import logging
from typing import Any, Dict, List, Tuple

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    VERSION,
    DOMAIN_DISPLAY_NAME,
    BINARY_SENSOR_MODEL,
    BINARY_SENSOR_DIAG_MODEL,
    BINARY_SENSOR_IS_WORKDAY,
    BINARY_SENSOR_IS_HOLIDAY,
    BINARY_SENSOR_IS_CUSTOM_HOLIDAY,
    BINARY_SENSOR_LEGAL_DIAG,
    BINARY_SENSOR_CUSTOM_DIAG,
    CONF_ENABLED_LEGAL_SENSOR,
    CONF_ENABLED_WORKDAY_SENSOR,
    CONF_ENABLED_CUSTOM_SENSOR,
    CONF_ENABLED_LEGAL_DIAG,
    CONF_ENABLED_CUSTOM_DIAG,
    ATTR_IS_WORKDAY,
    ATTR_IS_HOLIDAY,
    ATTR_IS_WEEKEND,
    ATTR_IS_SPECIAL_WORKDAY,
    ATTR_IS_CUSTOM_HOLIDAY,
    ATTR_ACTIVE_CUSTOM,
    ATTR_DAY_TYPE,
    KEY_LEGAL,
    KEY_CUSTOM,
)
from .coordinator import SmartWorkdayCoordinator, DayInfo

_LOGGER = logging.getLogger(__name__)

# (entity_name, icon, unique_suffix, DayInfo 属性名)
SENSOR_DEFS: List[Tuple[str, str, str, str]] = [
    (BINARY_SENSOR_IS_WORKDAY, "mdi:briefcase-check", "is_workday", "is_workday"),
    (BINARY_SENSOR_IS_HOLIDAY, "mdi:calendar-check", "is_holiday", "is_holiday"),
    (BINARY_SENSOR_IS_CUSTOM_HOLIDAY, "mdi:star", "is_custom_holiday", "is_custom_holiday"),
]

# entity_name → 启用开关键名（v3.1.0：每个传感器独立开关）
SENSOR_FLAG_MAP: Dict[str, str] = {
    BINARY_SENSOR_IS_WORKDAY: CONF_ENABLED_WORKDAY_SENSOR,
    BINARY_SENSOR_IS_HOLIDAY: CONF_ENABLED_LEGAL_SENSOR,
    BINARY_SENSOR_IS_CUSTOM_HOLIDAY: CONF_ENABLED_CUSTOM_SENSOR,
}


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
        """所有详细信息挂在 attributes 里（富信息）。

        v3.0.0：新增 active_custom 属性，暴露当日活跃的自定义类别明细。
        """
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
            ATTR_IS_CUSTOM_HOLIDAY: day_info.is_custom_holiday,
            ATTR_ACTIVE_CUSTOM: day_info.active_custom,
            "holiday_name": day_info.primary_event,
            "events": day_info.event_names,
            "upcoming": data.get("upcoming", []) if data else [],
        }


class SmartWorkdayDiagnosticBinarySensor(RestoreEntity, CoordinatorEntity, BinarySensorEntity):
    """诊断布尔传感器：检查数据源是否可用（有数据 = on，无数据 = off）。

    - 法定假期诊断：legal 数据非空 = on
    - 自定义假期诊断：custom 数据非空 = on
    详细诊断信息挂在 extra_state_attributes 里。
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, device_info, entity_name, icon, unique_suffix, kind):
        super().__init__(coordinator)
        self._kind = kind  # "legal" or "custom"
        self._attr_unique_id = f"{coordinator.entry_id}_{unique_suffix}"
        self._attr_name = entity_name
        self._attr_device_info = device_info
        self._attr_icon = icon

    def _get_raw_data(self) -> Dict[str, Any]:
        data = self.coordinator.data
        return data.get("data") if data else {}

    def _get_day_info(self) -> DayInfo | None:
        data = self.coordinator.data
        return data.get("day_info") if data else None

    @property
    def is_on(self) -> bool:
        """数据源非空 = on"""
        raw = self._get_raw_data()
        if self._kind == "legal":
            return len(raw.get(KEY_LEGAL, [])) > 0
        else:
            return len(raw.get(KEY_CUSTOM, [])) > 0

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        raw = self._get_raw_data()
        day_info = self._get_day_info()
        entries = raw.get(KEY_LEGAL if self._kind == "legal" else KEY_CUSTOM, [])
        if not entries:
            return {"data_count": 0}

        attrs: Dict[str, Any] = {
            "data_count": len(entries),
            "date": day_info.date if day_info else "",
            "weekday": day_info.weekday_name if day_info else "",
        }

        if self._kind == "legal":
            # 法定假期诊断：今天状态 + 下一个假期
            attrs["today_is_holiday"] = day_info.is_holiday if day_info else False
            attrs["today_event"] = day_info.primary_event if day_info else ""
            # 找下一个假期
            from datetime import date, datetime
            today = date.today()
            future = []
            for item in entries:
                start = None
                if "date" in item:
                    try:
                        start = datetime.strptime(item["date"], "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        pass
                elif "start" in item:
                    try:
                        start = datetime.strptime(item["start"], "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        pass
                if start and start > today:
                    future.append((item.get("name", "未命名"), start.isoformat(), (start - today).days))
            if future:
                future.sort(key=lambda x: x[2])
                attrs["next_holiday_name"] = future[0][0]
                attrs["next_holiday_date"] = future[0][1]
                attrs["days_until_next"] = future[0][2]
        else:
            # 自定义假期诊断：今天活跃类别
            attrs["today_active_custom"] = day_info.active_custom if day_info else {}
            attrs["today_is_custom_holiday"] = day_info.is_custom_holiday if day_info else False

        return attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置 3 个常规 + 2 个诊断 布尔传感器实体"""
    _LOGGER.debug("设置布尔传感器: %s", entry.entry_id)

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # 常规传感器 DeviceInfo
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data["name"],
        manufacturer=DOMAIN_DISPLAY_NAME,
        model=BINARY_SENSOR_MODEL,
        sw_version=VERSION,
    )

    # 诊断传感器 DeviceInfo（独立 model）
    diag_device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id + "_diag")},
        name=entry.data["name"] + " · 诊断",
        manufacturer=DOMAIN_DISPLAY_NAME,
        model=BINARY_SENSOR_DIAG_MODEL,
        sw_version=VERSION,
    )

    # v3.1.0：按开关筛选实体
    sensors = []
    for entity_name, icon, suffix, day_info_attr in SENSOR_DEFS:
        flag_key = SENSOR_FLAG_MAP.get(entity_name)
        if flag_key is not None:
            enabled = bool(entry.data.get(flag_key, True))
            if not enabled:
                continue
        sensors.append(SmartWorkdayBinarySensor(coordinator, device_info, entity_name, icon, suffix, day_info_attr))

    # 诊断传感器
    diag_defs = [
        (BINARY_SENSOR_LEGAL_DIAG, "mdi:heart-pulse", "legal_diag", "legal", CONF_ENABLED_LEGAL_DIAG),
        (BINARY_SENSOR_CUSTOM_DIAG, "mdi:heart-variant", "custom_diag", "custom", CONF_ENABLED_CUSTOM_DIAG),
    ]
    for entity_name, icon, suffix, kind, flag_key in diag_defs:
        enabled = bool(entry.data.get(flag_key, True))
        if not enabled:
            continue
        sensors.append(SmartWorkdayDiagnosticBinarySensor(coordinator, diag_device_info, entity_name, icon, suffix, kind))

    if sensors:
        async_add_entities(sensors)
    _LOGGER.info("已添加 %d 个布尔传感器实体", len(sensors))
