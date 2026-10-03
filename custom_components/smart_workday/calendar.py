"""Calendar platform for Smart Workday - 单一日历实体，事件 description 标注来源类型。"""

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

from .const import (
    DOMAIN,
    VERSION,
    DEFAULT_NAME,
    DOMAIN_DISPLAY_NAME,
    CALENDAR_ENTITY_NAME,
    CALENDAR_MODEL,
    CALENDAR_UNIQUE_SUFFIX,
    EVENT_SOURCE_LEGAL,
    EVENT_SOURCE_STUDENT,
    EVENT_SOURCE_CUSTOM,
    EVENT_SOURCE_MAKEUP,
    SOURCE_TO_CATEGORY,
    STUDENT_HOLIDAY_KEYWORDS,
    MAKEUP_KEYWORD,
)
from .coordinator import SmartWorkdayCoordinator

_LOGGER = logging.getLogger(__name__)


class SmartWorkdayCalendar(CoordinatorEntity, CalendarEntity):
    """单一日历实体 - 显示所有类型的假期事件，description 标注来源。"""

    _attr_has_entity_name = True
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
    )
    _attr_icon = "mdi:calendar-variant"

    def __init__(self, coordinator: SmartWorkdayCoordinator, device_info: DeviceInfo):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}{CALENDAR_UNIQUE_SUFFIX}"
        self._attr_name = CALENDAR_ENTITY_NAME
        self._attr_device_info = device_info
        self._attr_sw_version = VERSION
        self._event_list: List[CalendarEvent] = []

    @property
    def _enabled_flags(self) -> dict:
        """从 data_manager 读取顶层开关（默认 True 向后兼容）"""
        return getattr(
            self.coordinator.data_manager,
            "_enabled_flags",
            {"legal": True, "student": True, "custom": True},
        )

    def _create_event(self, start_date, end_date, name, uid: str = "",
                      source: str = "") -> CalendarEvent:
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

        # 描述标注类型（用于日历 UI 显示来源 + 删除时推断分类）
        if MAKEUP_KEYWORD in name:
            description = EVENT_SOURCE_MAKEUP
        else:
            description = source

        return CalendarEvent(
            start=event_start,
            end=event_end,
            summary=name,
            description=description,
            uid=uid,
        )

    async def _generate_events(self) -> List[CalendarEvent]:
        """生成日历事件（顶层开关关闭的分类不显示）"""
        events = []
        data = await self.coordinator.data_manager.get_calendar_events()
        flags = self._enabled_flags

        # 法定假期
        if flags.get("legal"):
            for item in data.get("holidays", []):
                events.append(self._create_event(
                    item.get("date") or item.get("start"),
                    item.get("date") or item.get("end"),
                    item.get("name", "法定假期"),
                    item.get("uid", ""),
                    EVENT_SOURCE_LEGAL,
                ))

        # 学生假期（条目 enabled 过滤）
        if flags.get("student"):
            for item in data.get("studentdays", []):
                if not item.get("enabled", True):
                    continue
                events.append(self._create_event(
                    item.get("date") or item.get("start"),
                    item.get("date") or item.get("end"),
                    item.get("name", "学生假期"),
                    item.get("uid", ""),
                    EVENT_SOURCE_STUDENT,
                ))

        # 自定义假期
        if flags.get("custom"):
            for item in data.get("customdays", []):
                events.append(self._create_event(
                    item.get("date") or item.get("start"),
                    item.get("date") or item.get("end"),
                    item.get("name", "自定义假期"),
                    item.get("uid", ""),
                    EVENT_SOURCE_CUSTOM,
                ))

        _LOGGER.debug("生成日历事件: %d 个", len(events))
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
            _LOGGER.debug("日历更新完成，共 %d 个事件", len(self._event_list))
        except Exception as e:
            _LOGGER.error("更新日历失败: %s", e)

    # ---------- 日历 UI 原生增删支持 ----------

    async def async_create_event(self, **kwargs) -> CalendarEvent:
        """通过日历 UI 创建事件 - 通过 description 推断类型"""
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

        # 推断分类：
        # 1) 若 description 匹配已知来源前缀 → 用对应分类
        # 2) 若名称含"调休" → 法定假期
        # 3) 若名称含"学生"或"寒/暑/春/秋/儿童节" → 学生假期
        # 4) 默认归为自定义
        category = None
        for src, cat in SOURCE_TO_CATEGORY.items():
            if description and description.startswith(src):
                category = cat
                break
        if category is None:
            if MAKEUP_KEYWORD in summary:
                category = "holidays"
            elif any(kw in summary for kw in STUDENT_HOLIDAY_KEYWORDS):
                category = "studentdays"
            else:
                category = "customdays"

        dm = self.coordinator.data_manager
        await dm.add_entry(category, summary, start_str, end_str, description)
        await self.coordinator.async_request_refresh()

        _LOGGER.info(
            "日历UI添加: [%s] %s (%s~%s)",
            category, summary, start_str, end_str
        )

        return self._create_event(start_str, end_str, summary, "", description)

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
    """设置单一日历实体"""
    _LOGGER.debug("设置日历: %s", entry.entry_id)

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get("name", DEFAULT_NAME),
        manufacturer=DOMAIN_DISPLAY_NAME,
        model=CALENDAR_MODEL,
        sw_version=VERSION,
    )

    async_add_entities([SmartWorkdayCalendar(coordinator, device_info)])
    _LOGGER.info("已添加日历实体")
