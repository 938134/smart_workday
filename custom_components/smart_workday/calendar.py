"""Calendar platform for Smart Workday - 3 个独立日历实体，按分类区分。

- 法定假期日历：显示/添加/删除 holidays 分类（含调休）
- 学生假期日历：显示/添加/删除 studentdays 分类
- 自定义假期日历：显示/添加/删除 customdays 分类

用户在 HA 日历 UI 的下拉菜单里选哪个日历添加事件，就自动归入对应分类。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt

from .const import (
    DOMAIN,
    VERSION,
    DEFAULT_NAME,
    DOMAIN_DISPLAY_NAME,
    CALENDAR_MODEL,
    CALENDAR_LEGAL_NAME,
    CALENDAR_STUDENT_NAME,
    CALENDAR_CUSTOM_NAME,
    CALENDAR_LEGAL_SUFFIX,
    CALENDAR_STUDENT_SUFFIX,
    CALENDAR_CUSTOM_SUFFIX,
    CONF_ENABLED_LEGAL,
    CONF_ENABLED_STUDENT,
    CONF_ENABLED_CUSTOM,
    EVENT_SOURCE_LEGAL,
    EVENT_SOURCE_STUDENT,
    EVENT_SOURCE_CUSTOM,
    EVENT_SOURCE_MAKEUP,
    MAKEUP_KEYWORD,
)
from .coordinator import SmartWorkdayCoordinator

_LOGGER = logging.getLogger(__name__)

# 分类 → (数据键, 日历名称, unique_id 后缀, 事件来源, 顶层开关键, 图标)
CATEGORY_CONFIG: Dict[str, Tuple[str, str, str, str, str, str]] = {
    "holidays": (
        "holidays",
        CALENDAR_LEGAL_NAME,
        CALENDAR_LEGAL_SUFFIX,
        EVENT_SOURCE_LEGAL,
        CONF_ENABLED_LEGAL,
        "mdi:calendar-star",
    ),
    "studentdays": (
        "studentdays",
        CALENDAR_STUDENT_NAME,
        CALENDAR_STUDENT_SUFFIX,
        EVENT_SOURCE_STUDENT,
        CONF_ENABLED_STUDENT,
        "mdi:school",
    ),
    "customdays": (
        "customdays",
        CALENDAR_CUSTOM_NAME,
        CALENDAR_CUSTOM_SUFFIX,
        EVENT_SOURCE_CUSTOM,
        CONF_ENABLED_CUSTOM,
        "mdi:star-circle",
    ),
}


class SmartWorkdayCalendar(CoordinatorEntity, CalendarEntity):
    """单个分类的日历实体 - 只显示/接受自己分类的事件。"""

    _attr_has_entity_name = True
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
    )

    def __init__(self, coordinator: SmartWorkdayCoordinator, device_info: DeviceInfo,
                 category: str):
        super().__init__(coordinator)
        self._category = category
        data_key, name, suffix, source, flag_key, icon = CATEGORY_CONFIG[category]
        self._data_key = data_key
        self._source = source
        self._flag_key = flag_key
        self._attr_unique_id = f"{coordinator.entry_id}{suffix}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = device_info
        self._attr_sw_version = VERSION
        self._event_list: List[CalendarEvent] = []

    # ---------- 开关与时区 ----------

    @property
    def _enabled(self) -> bool:
        """该分类是否启用（顶层开关）"""
        flags = getattr(self.coordinator.data_manager, "_enabled_flags", {})
        return bool(flags.get(self._flag_key, True))

    def _get_tz(self) -> datetime.tzinfo:
        """获取 HA 系统时区"""
        try:
            return ZoneInfo(self.hass.config.time_zone)
        except Exception:
            return ZoneInfo("UTC")

    # ---------- 事件构建 ----------

    def _create_event(self, start_date, end_date, name: str, uid: str = "",
                      tz: Optional[datetime.tzinfo] = None) -> CalendarEvent:
        """创建日历事件"""
        # 解析开始日期
        if isinstance(start_date, str):
            try:
                start = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                start = datetime.now().date()
        else:
            start = start_date if hasattr(start_date, "year") else datetime.now().date()

        # 解析结束日期（单天事件 end_date 可能为 None 或等于 start）
        if end_date is None or end_date == start_date:
            end = start
        else:
            if isinstance(end_date, str):
                try:
                    end = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    end = start
            else:
                end = end_date

        event_start = datetime.combine(start, datetime.min.time())
        event_end = datetime.combine(end + timedelta(days=1), datetime.min.time())

        # 补齐时区
        if tz is None:
            tz = self._get_tz()
        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=tz)
        if event_end.tzinfo is None:
            event_end = event_end.replace(tzinfo=tz)

        # 描述标注类型（法定日历中区分调休）
        if self._category == "holidays" and MAKEUP_KEYWORD in name:
            description = EVENT_SOURCE_MAKEUP
        else:
            description = self._source

        return CalendarEvent(
            start=event_start,
            end=event_end,
            summary=name,
            description=description,
            uid=uid,
        )

    async def _generate_events(self) -> List[CalendarEvent]:
        """生成当前分类的日历事件"""
        events = []
        data = await self.coordinator.data_manager.get_calendar_events()
        tz = self._get_tz()

        for item in data.get(self._data_key, []):
            if not isinstance(item, dict):
                continue
            # 学生假期支持条目级 enabled 过滤
            if self._category == "studentdays" and not item.get("enabled", True):
                continue
            events.append(self._create_event(
                item.get("date") or item.get("start"),
                item.get("date") or item.get("end"),
                item.get("name", self._attr_name),
                item.get("uid", ""),
                tz,
            ))

        _LOGGER.debug("生成 %s 事件: %d 个", self._attr_name, len(events))
        return events

    async def async_get_events(self, hass, start_date, end_date) -> List[CalendarEvent]:
        """获取时间段内的事件"""
        tz = self._get_tz()
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=tz)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=tz)

        all_events = await self._generate_events()
        return [
            e for e in all_events
            if e.start <= end_date and e.end >= start_date
        ]

    @property
    def event(self) -> Optional[CalendarEvent]:
        """返回下一个即将发生的事件"""
        if not self._event_list:
            return None
        now = dt.now()
        future = [e for e in self._event_list if e.start > now]
        return min(future, key=lambda e: e.start) if future else None

    async def async_update(self) -> None:
        """更新日历事件"""
        try:
            self._event_list = await self._generate_events()
            _LOGGER.debug("%s 更新完成，共 %d 个事件", self._attr_name, len(self._event_list))
        except Exception as e:
            _LOGGER.error("更新 %s 失败: %s", self._attr_name, e)

    # ---------- 日历 UI 原生增删支持 ----------

    async def async_create_event(self, **kwargs) -> CalendarEvent:
        """通过日历 UI 创建事件 - 自动归入当前分类

        用户在哪个日历上添加，就存入哪个分类，无需指定类型。
        法定日历中若名称含"调休"，自动标记为调休上班日。
        """
        summary = (kwargs.get("summary") or "").strip()
        if not summary:
            raise ValueError("事件名称不能为空")

        start_dt = kwargs.get("start_date") or kwargs.get("start")
        end_dt = kwargs.get("end_date") or kwargs.get("end")
        description = kwargs.get("description", "") or ""

        if start_dt is None:
            raise ValueError("开始日期不能为空")

        # 转 YYYY-MM-DD 字符串
        start_str = start_dt.strftime("%Y-%m-%d") if hasattr(start_dt, "strftime") else str(start_dt)[:10]
        end_str = None
        if end_dt is not None:
            end_str = end_dt.strftime("%Y-%m-%d") if hasattr(end_dt, "strftime") else str(end_dt)[:10]

        dm = self.coordinator.data_manager
        await dm.add_entry(self._data_key, summary, start_str, end_str, description)
        await self.coordinator.async_request_refresh()

        _LOGGER.info(
            "日历UI添加: [%s] %s (%s~%s)",
            self._attr_name, summary, start_str, end_str
        )

        return self._create_event(start_str, end_str, summary, "")

    async def async_delete_event(self, uid: str, **kwargs) -> None:
        """通过日历 UI 删除事件（仅删除本分类）"""
        if not uid:
            raise ValueError("删除事件需要 uid")

        dm = self.coordinator.data_manager
        # 只在当前分类中查找
        data = await dm.get_calendar_events()
        items = data.get(self._data_key, [])
        found = any(
            isinstance(item, dict) and item.get("uid") == uid
            for item in items
        )
        if not found:
            raise ValueError(f"未在本日历中找到 uid={uid} 的事件")

        deleted = await dm.delete_entry_by_uid(uid)
        if not deleted:
            raise ValueError(f"未找到 uid={uid} 的假期条目")

        await self.coordinator.async_request_refresh()
        _LOGGER.info("日历UI删除: [%s] uid=%s", self._attr_name, uid)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置 3 个分类日历实体"""
    _LOGGER.debug("设置日历: %s", entry.entry_id)

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get("name", DEFAULT_NAME),
        manufacturer=DOMAIN_DISPLAY_NAME,
        model=CALENDAR_MODEL,
        sw_version=VERSION,
    )

    entities = [
        SmartWorkdayCalendar(coordinator, device_info, category)
        for category in CATEGORY_CONFIG
    ]
    async_add_entities(entities)
    _LOGGER.info("已添加 %d 个日历实体", len(entities))
