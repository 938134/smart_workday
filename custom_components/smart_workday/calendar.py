"""Calendar platform for Smart Workday - 3 个独立日历实体（法定/学生/自定义）."""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

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

from .const import DOMAIN, CalendarType
from .coordinator import SmartWorkdayCoordinator

_LOGGER = logging.getLogger(__name__)

# 日历类型 → 显示名称
CALENDAR_NAMES = {
    CalendarType.LEGAL: "法定节假日日历",
    CalendarType.STUDENT: "学生假期日历",
    CalendarType.CUSTOM: "自定义假期日历",
}

# 日历类型 → 图标
CALENDAR_ICONS = {
    CalendarType.LEGAL: "mdi:calendar-star",
    CalendarType.STUDENT: "mdi:school",
    CalendarType.CUSTOM: "mdi:star-circle",
}


class SmartWorkdayCalendar(CoordinatorEntity, CalendarEntity):
    """日历实体 - 每个类型独立一个日历，事件自动归类"""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartWorkdayCoordinator, device_info: DeviceInfo,
                 cal_type: CalendarType):
        super().__init__(coordinator)
        self._cal_type = cal_type
        self._attr_unique_id = f"{coordinator.entry_id}_calendar_{cal_type.value}"
        self._attr_name = CALENDAR_NAMES[cal_type]
        self._attr_icon = CALENDAR_ICONS[cal_type]
        self._attr_device_info = device_info
        self._attr_supported_features = (
            CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
        )
        self._event_list: List[CalendarEvent] = []

    @property
    def _data_category(self) -> str:
        """日历类型 → 数据分类键"""
        return self._cal_type.data_category

    def _create_event(self, start_date, end_date, name, uid: str = "") -> CalendarEvent:
        """创建日历事件"""
        # 解析开始日期
        if isinstance(start_date, str):
            parsed = dt.parse_date(start_date)
            start = parsed if parsed else datetime.strptime(start_date, "%Y-%m-%d").date()
        else:
            start = start_date

        # 解析结束日期（单天事件 end_date 可能为 None 或等于 start）
        if end_date is None or end_date == start_date:
            end = start
        else:
            if isinstance(end_date, str):
                parsed = dt.parse_date(end_date)
                end = parsed if parsed else datetime.strptime(end_date, "%Y-%m-%d").date()
            else:
                end = end_date

        event_start = datetime.combine(start, datetime.min.time())
        event_end = datetime.combine(end + timedelta(days=1), datetime.min.time())

        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=dt.DEFAULT_TIME_ZONE)
        if event_end.tzinfo is None:
            event_end = event_end.replace(tzinfo=dt.DEFAULT_TIME_ZONE)

        # 描述标注类型
        desc_map = {
            CalendarType.LEGAL: "法定节假日",
            CalendarType.STUDENT: "学生假期",
            CalendarType.CUSTOM: "自定义假期",
        }
        description = desc_map.get(self._cal_type, "")
        if "调休" in name:
            description = "调休上班日"

        return CalendarEvent(
            start=event_start,
            end=event_end,
            summary=name,
            description=description,
            uid=uid,
        )

    async def _generate_events(self) -> List[CalendarEvent]:
        """生成当前日历类型的所有事件"""
        events = []
        data = await self.coordinator.data_manager.get_calendar_events()

        category = self._data_category
        for item in data.get(category, []):
            # 新格式：enabled=False 的条目不出现在日历上（向后兼容）
            if category == "studentdays" and not item.get("enabled", True):
                continue
            uid = item.get("uid", "")
            name = item.get("name", "")
            if "date" in item:
                events.append(self._create_event(
                    item["date"], item["date"], name, uid
                ))
            elif "start" in item and "end" in item:
                events.append(self._create_event(
                    item["start"], item["end"], name, uid
                ))

        _LOGGER.debug("生成 %s 日历事件: %d 个", self._cal_type.display_name, len(events))
        return events

    async def async_get_events(self, hass, start_date, end_date) -> List[CalendarEvent]:
        """获取时间段内的事件"""
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=dt.DEFAULT_TIME_ZONE)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=dt.DEFAULT_TIME_ZONE)

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
            _LOGGER.debug("%s 日历更新完成，共 %d 个事件", self._cal_type.display_name, len(self._event_list))
        except Exception as e:
            _LOGGER.error("更新日历失败: %s", e)

    # ---------- 日历 UI 原生增删支持 ----------

    async def async_create_event(self, **kwargs) -> CalendarEvent:
        """通过日历 UI 创建事件 - 自动归入当前日历类型"""
        summary = kwargs.get("summary", "").strip()
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

        # 直接归入当前日历类型
        category = self._data_category
        dm = self.coordinator.data_manager
        await dm.add_entry(category, summary, start_str, end_str, description)
        # 刷新协调器，让传感器立即感知
        await self.coordinator.async_request_refresh()

        _LOGGER.info(
            "%s 日历添加: %s (%s~%s)",
            self._cal_type.display_name, summary, start_str, end_str
        )

        return self._create_event(start_str, end_str, summary, "")

    async def async_delete_event(self, uid: str, **kwargs) -> None:
        """通过日历 UI 删除事件"""
        if not uid:
            raise ValueError("删除事件需要 uid")

        dm = self.coordinator.data_manager
        deleted = await dm.delete_entry_by_uid(uid)
        if not deleted:
            raise ValueError(f"未找到 uid={uid} 的假期条目")

        await self.coordinator.async_request_refresh()
        _LOGGER.info("日历UI删除假期: uid=%s", uid)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置 3 个日历实体（法定/学生/自定义）"""
    _LOGGER.debug("设置日历: %s", entry.entry_id)

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get("name", "智能工作日"),
        manufacturer="Smart Workday",
        model="工作日传感器",
        sw_version="2.4.0",
    )

    calendars = [
        SmartWorkdayCalendar(coordinator, device_info, cal_type)
        for cal_type in CalendarType
    ]
    async_add_entities(calendars)
    _LOGGER.info("已添加 %d 个日历实体", len(calendars))
