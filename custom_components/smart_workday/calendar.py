"""Calendar platform for Smart Workday."""

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

from .const import DOMAIN, HolidayType, ATTR_CURRENT_TYPE
from .coordinator import SmartWorkdayCoordinator

_LOGGER = logging.getLogger(__name__)

# description 关键词 → 分类映射（用户在日历 UI 填描述时用关键词指定类型）
DESC_KEYWORD_STUDENT = "学生"
DESC_KEYWORD_MAKEUP = "调休"


class SmartWorkdayCalendar(CoordinatorEntity, CalendarEntity):
    """日历实体 - 显示所有假期，支持日历 UI 直接增删"""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartWorkdayCoordinator, device_info: DeviceInfo):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_calendar"
        self._attr_name = "假期日历"
        self._attr_icon = "mdi:calendar-month"
        self._attr_device_info = device_info
        self._attr_supported_features = (
            CalendarEntityFeature.CREATE | CalendarEntityFeature.DELETE
        )
        self._event_list: List[CalendarEvent] = []

    def _create_event(self, start_date, end_date, name, source, uid: str = "") -> CalendarEvent:
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

        return CalendarEvent(
            start=event_start,
            end=event_end,
            summary=name,
            description="调休上班日" if "调休" in name else source,
            uid=uid,
        )

    async def _generate_events(self) -> List[CalendarEvent]:
        """生成所有事件"""
        events = []
        data = await self.coordinator.data_manager.get_calendar_events()

        for source in ["holidays", "customdays", "studentdays"]:
            for item in data.get(source, []):
                uid = item.get("uid", "")
                name = item.get("name", "")
                if "date" in item:
                    events.append(self._create_event(
                        item["date"], item["date"], name, source, uid
                    ))
                elif "start" in item and "end" in item:
                    events.append(self._create_event(
                        item["start"], item["end"], name, source, uid
                    ))

        _LOGGER.debug("生成了 %d 个日历事件", len(events))
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

    @staticmethod
    def _classify_by_keywords(name: str, description: str) -> "HolidayType":
        """向后兼容：根据描述关键词判断假期类型

        主推方式是用 select 实体选类型，这里仅作兜底。
        - 描述含「学生」→ STUDENT
        - 描述含「调休」或名称含「调休」→ MAKEUP
        - 其他 → CUSTOM
        """
        desc = (description or "").lower()
        nm = name or ""
        if DESC_KEYWORD_STUDENT in desc:
            return HolidayType.STUDENT
        if DESC_KEYWORD_MAKEUP in desc or "调休" in nm:
            return HolidayType.MAKEUP
        return HolidayType.CUSTOM

    async def async_create_event(self, **kwargs) -> CalendarEvent:
        """通过日历 UI 创建事件

        类型判定优先级：
        1. 读取「假期类型」select 实体的当前值（主推方式）
        2. 向后兼容：description 含关键词时按关键词分类
        3. 兜底：默认自定义假期
        """
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

        # 确定假期类型
        htype = self._resolve_holiday_type(summary, description)

        # 调休名称自动补后缀
        if htype.is_makeup and "调休" not in summary:
            summary = f"{summary}调休"

        category = htype.data_category

        dm = self.coordinator.data_manager
        await dm.add_entry(category, summary, start_str, end_str, description)
        # 刷新协调器，让传感器立即感知
        await self.coordinator.async_request_refresh()

        _LOGGER.info(
            "日历UI添加假期: [%s/%s] %s (%s~%s)",
            category, htype.display_name, summary, start_str, end_str
        )

        return self._create_event(start_str, end_str, summary, category, "")

    def _resolve_holiday_type(self, summary: str, description: str) -> "HolidayType":
        """确定假期类型

        优先读 select 实体的当前值；
        选「法定假日」时名称/描述含「调休」→ 自动归为调休上班日（随法定节假日一起设定）；
        向后兼容：description 含关键词时按关键词分类。
        """
        # 1. 读 hass.data 里 select 实体存的当前类型
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.coordinator.entry_id, {})
        current_type_value = entry_data.get(ATTR_CURRENT_TYPE)

        if current_type_value:
            try:
                htype = HolidayType(current_type_value)
                # 调休补班合并进法定假日：选「法定假日」且名称/描述含「调休」→ 调休上班日
                if htype == HolidayType.LEGAL and (
                    DESC_KEYWORD_MAKEUP in (description or "")
                    or "调休" in (summary or "")
                ):
                    return HolidayType.MAKEUP
                return htype
            except ValueError:
                _LOGGER.warning("未知的当前类型值: %s，按关键词分类", current_type_value)

        # 2. 向后兼容：description 关键词分类
        return self._classify_by_keywords(summary, description)

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
    """设置日历实体"""
    _LOGGER.debug("设置日历: %s", entry.entry_id)
    
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get("name", "智能工作日"),
        manufacturer="Smart Workday",
        model="工作日传感器",
        sw_version="2.2.0",
    )
    
    calendar = SmartWorkdayCalendar(coordinator, device_info)
    async_add_entities([calendar])
    _LOGGER.info("已添加日历实体")