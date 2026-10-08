"""Calendar platform for Smart Workday - 单日历合并显示所有分类事件。

v3.0.0 破坏性重构：
- description 前缀从 3 分类（法定/学生/自定义）简化为 2 分类（法定/自定义）
- 自定义条目在 description 里追加类别：🎉 自定义假期 · 学生
- 事件构建遍历 dm.iter_enabled_items()，只区分 kind="legal" / kind="custom"
"""

import logging
from datetime import datetime, timedelta, date as date_type
from typing import List, Optional
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
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt

from .const import (
    DOMAIN,
    VERSION,
    DOMAIN_DISPLAY_NAME,
    CALENDAR_ENTITY_NAME,
    CALENDAR_UNIQUE_SUFFIX,
    EVENT_SOURCE_LEGAL,
    EVENT_SOURCE_CUSTOM,
    EVENT_SOURCE_MAKEUP,
    MAKEUP_KEYWORD,
)
from .coordinator import SmartWorkdayCoordinator

_LOGGER = logging.getLogger(__name__)


class SmartWorkdayCalendar(RestoreEntity, CoordinatorEntity, CalendarEntity):
    """单日历实体 - 显示所有分类事件，description 标注来源。"""

    _attr_has_entity_name = True
    _attr_supported_features = CalendarEntityFeature.DELETE_EVENT

    def __init__(self, coordinator: SmartWorkdayCoordinator, device_info: DeviceInfo):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}{CALENDAR_UNIQUE_SUFFIX}"
        self._attr_name = CALENDAR_ENTITY_NAME
        self._attr_device_info = device_info
        self._attr_icon = "mdi:calendar-month"
        self._event_list: List[CalendarEvent] = []
        # 时区对象（HA 启动时确定）
        try:
            self._tz = ZoneInfo(self.hass.config.time_zone)
        except Exception:
            self._tz = ZoneInfo("UTC")

    # ---------- 事件构建 ----------

    @staticmethod
    def _parse_date(value) -> Optional[date_type]:
        """解析 YYYY-MM-DD 字符串为 date（兼容 date 对象传入）"""
        if isinstance(value, date_type):
            return value
        if isinstance(value, str):
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None
        return None

    def _create_event(self, start_str, end_str, name: str, uid: str,
                      description: str) -> Optional[CalendarEvent]:
        """创建日历事件（start_str 为空或解析失败时返回 None）。

        v2.19.1：多日事件的 summary 追加日期范围（如 "国庆节 (10-01~10-08)"），
        让 calendar 实体在 UI 上直接显示假期范围；单日事件保持原名。
        """
        start = self._parse_date(start_str)
        if start is None:
            _LOGGER.warning("跳过事件 '%s'：开始日期为空或解析失败", name)
            return None

        end = self._parse_date(end_str) if end_str and end_str != start_str else start
        if end is None:
            end = start

        # 多日事件在 summary 里带日期范围，UI 上直接可见
        if start == end:
            summary = name
        else:
            summary = f"{name} ({start.strftime('%m-%d')}~{end.strftime('%m-%d')})"

        return CalendarEvent(
            start=datetime.combine(start, datetime.min.time(), self._tz),
            end=datetime.combine(end + timedelta(days=1), datetime.min.time(), self._tz),
            summary=summary,
            description=description,
            uid=uid,
        )

    def _build_events(self, data: dict) -> List[CalendarEvent]:
        """从原始数据字典构建 CalendarEvent 列表"""
        dm = self.coordinator.data_manager
        events: List[CalendarEvent] = []

        for kind, item in dm.iter_enabled_items(data):
            name = item["name"]
            if kind == "legal":
                desc = EVENT_SOURCE_MAKEUP if MAKEUP_KEYWORD in name else EVENT_SOURCE_LEGAL
            else:  # custom
                category = item.get("category") or "自定义"
                desc = f"{EVENT_SOURCE_CUSTOM} · {category}"

            start = item.get("date") or item.get("start")
            end = item.get("date") or item.get("end")
            ev = self._create_event(start, end, name, item["uid"], desc)
            if ev:
                events.append(ev)

        return events

    async def async_get_events(self, hass, start_date, end_date) -> List[CalendarEvent]:
        """获取时间段内的事件"""
        try:
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=self._tz)
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=self._tz)

            # 优先用缓存
            if self._event_list:
                all_events = self._event_list
            else:
                data = self.coordinator.data.get("data") if self.coordinator.data else None
                if not data:
                    data = self.coordinator.data_manager._data_cache
                if not data:
                    _LOGGER.warning("async_get_events: 无任何可用数据")
                    return []
                all_events = self._build_events(data)
                if all_events:
                    self._event_list = all_events

            return [e for e in all_events if e.start <= end_date and e.end >= start_date]
        except Exception as e:
            _LOGGER.error("async_get_events 失败: %s", e, exc_info=True)
            return []

    @property
    def event(self) -> Optional[CalendarEvent]:
        """返回当前/最近事件（三级优先级：进行中 > 未来 > 今天）

        优先读 _event_list 缓存（由 async_update 填充）；
        缓存为空时同步构建兜底，避免 HA 感知不到事件。
        """
        try:
            events = self._event_list
            if not events:
                data = self.coordinator.data.get("data") if self.coordinator.data else None
                if not data:
                    data = self.coordinator.data_manager._data_cache
                if not data:
                    return None
                events = self._build_events(data)
                if events:
                    self._event_list = events
            if not events:
                return None

            now = dt.now()
            # 优先级 1：进行中
            ongoing = [e for e in events if e.start <= now < e.end]
            if ongoing:
                return min(ongoing, key=lambda e: e.start)
            # 优先级 2：未来最近
            future = [e for e in events if e.start > now]
            if future:
                return min(future, key=lambda e: e.start)
            # 优先级 3：今天内
            today_events = [
                e for e in events
                if e.start.date() == now.date() or e.end.date() == now.date()
            ]
            if today_events:
                return min(today_events, key=lambda e: e.start)
            return None
        except Exception as e:
            _LOGGER.error("event 属性计算失败: %s", e, exc_info=True)
            return None

    async def async_update(self) -> None:
        """CalendarEntity 请求时刷新事件缓存"""
        try:
            data = self.coordinator.data.get("data") if self.coordinator.data else None
            if not data:
                data = self.coordinator.data_manager._data_cache
            if not data:
                return
            self._event_list = self._build_events(data)
        except Exception as e:
            _LOGGER.error("async_update 失败: %s", e, exc_info=True)

    # ---------- 日历 UI 删除支持 ----------

    async def async_delete_event(self, uid: str, **kwargs) -> None:
        """通过日历 UI 删除事件"""
        if not uid:
            raise ValueError("删除事件需要 uid")

        deleted = await self.coordinator.data_manager.delete_entry_by_uid(uid)
        if not deleted:
            raise ValueError(f"未找到 uid={uid} 的事件")

        self._event_list = []  # 清空缓存，等待刷新
        await self.coordinator.async_request_refresh()
        _LOGGER.info("日历UI删除: uid=%s", uid)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置单日历实体"""
    _LOGGER.debug("设置日历: %s", entry.entry_id)

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data["name"],
        manufacturer=DOMAIN_DISPLAY_NAME,
        model=CALENDAR_ENTITY_NAME,
        sw_version=VERSION,
    )

    async_add_entities([SmartWorkdayCalendar(coordinator, device_info)])
    _LOGGER.info("已添加 %s 实体", CALENDAR_ENTITY_NAME)
