"""Calendar platform for Smart Workday - 单日历合并显示所有分类事件。

- 显示所有分类事件（法定/学生/自定义），description 标注来源
- 仅支持 DELETE_EVENT（录入走 OptionsFlow 表单）
- 数据从 coordinator.data["data"] 缓存读取，兜底 _data_cache

v2.18.5 关键修复：
- 显式覆盖 `available` property 返回 True，
  防止 coordinator 刷新失败时日历整块变"不可用"
  （v2.16.0 误删了这个覆盖，是"日历不可用"的根本原因）
- `_attr_state` / `_attr_available` 同步写入，
  HA 2026.5+ 历史系统直接读取 _attr_state，None 会记为 unavailable

v2.18.6 尝试失败：
- 覆盖 state property 返回 "国庆节 2026-10-04" → HA 内部对自定义字符串格式
  处理异常，配置后立刻在 Logbook 记录"不可用"

v2.18.7 修复（回退 state 覆盖）：
- 删除 state property 覆盖（HA CalendarEntity.state 有 @final，覆盖有副作用）
- 保留 write_ha_state 覆盖：写状态前强制 _attr_available=True
  防止 CoordinatorEntity.last_update_success 抖动污染 _attr_available
- 保留 available property 覆盖：返回 True + 内部同步 _attr_available=True
- 依赖 __init__ 里 _attr_state="空闲" + async_update 里同步 _attr_state
  让 HA 走默认 state 处理，Logbook 记录 "空闲"/"国庆节" 字符串
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
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt

from .const import (
    DOMAIN,
    VERSION,
    DOMAIN_DISPLAY_NAME,
    CALENDAR_ENTITY_NAME,
    CALENDAR_UNIQUE_SUFFIX,
    EVENT_SOURCE_LEGAL,
    EVENT_SOURCE_STUDENT,
    EVENT_SOURCE_CUSTOM,
    EVENT_SOURCE_MAKEUP,
    MAKEUP_KEYWORD,
)
from .coordinator import SmartWorkdayCoordinator

_LOGGER = logging.getLogger(__name__)


class SmartWorkdayCalendar(CoordinatorEntity, CalendarEntity):
    """单日历实体 - 显示所有分类事件，description 标注来源。"""

    _attr_has_entity_name = True
    _attr_supported_features = CalendarEntityFeature.DELETE_EVENT

    def __init__(self, coordinator: SmartWorkdayCoordinator, device_info: DeviceInfo):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}{CALENDAR_UNIQUE_SUFFIX}"
        self._attr_name = CALENDAR_ENTITY_NAME
        self._attr_device_info = device_info
        self._attr_sw_version = VERSION
        self._attr_icon = "mdi:calendar-month"
        self._event_list: List[CalendarEvent] = []
        # ⚠️ 关键：显式设初始 state 让 HA 历史系统从启动就有值（None 会记为 unavailable）
        self._attr_state = "空闲"
        self._attr_available = True
        # 时区对象（HA 启动时确定）
        try:
            self._tz = ZoneInfo(self.hass.config.time_zone)
        except Exception:
            self._tz = ZoneInfo("UTC")

    @property
    def available(self) -> bool:
        """显式返回 True：即使 coordinator 刷新失败，日历也不变 unavailable。

        ⚠️ CoordinatorEntity 默认让 available 跟随 coordinator.last_update_success，
        一旦 _async_update_data 抛 UpdateFailed，整个日历会变"不可用"。
        日历的数据兜底走 data_manager._data_cache（不依赖 coordinator.data），
        所以 coordinator 短暂失败不影响日历展示。

        同步设置 _attr_available=True，防止 HA write_ha_state 读到 False 就把 state 覆盖为 unavailable。
        """
        self._attr_available = True
        return True

    def write_ha_state(self, *args, **kwargs) -> None:
        """覆盖 HA 的 write_ha_state，强制 _attr_available 为 True。

        HA 2026.5+ 中 write_ha_state 直接读 _attr_available，
        若为 False 会把 state 强制设为 None（Logbook 记为 unavailable）。
        CoordinatorEntity 的 last_update_success 抖动会通过 MRO 间接污染 _attr_available，
        所以每次写状态前强制重置为 True。
        """
        self._attr_available = True
        super().write_ha_state(*args, **kwargs)

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
        """创建日历事件（start_str 为空或解析失败时返回 None）"""
        start = self._parse_date(start_str)
        if start is None:
            _LOGGER.warning("跳过事件 '%s'：开始日期为空或解析失败", name)
            return None

        end = self._parse_date(end_str) if end_str and end_str != start_str else start
        if end is None:
            end = start

        return CalendarEvent(
            start=datetime.combine(start, datetime.min.time(), self._tz),
            end=datetime.combine(end + timedelta(days=1), datetime.min.time(), self._tz),
            summary=name,
            description=description,
            uid=uid,
        )

    def _build_events(self, data: dict) -> List[CalendarEvent]:
        """从原始数据字典构建 CalendarEvent 列表"""
        dm = self.coordinator.data_manager
        events: List[CalendarEvent] = []

        for category, item in dm.iter_enabled_items(data):
            name = item["name"]
            if category == "holiday":
                desc = EVENT_SOURCE_MAKEUP if MAKEUP_KEYWORD in name else EVENT_SOURCE_LEGAL
            elif category == "student":
                desc = EVENT_SOURCE_STUDENT
            else:  # custom
                desc = EVENT_SOURCE_CUSTOM

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
        """CalendarEntity 请求时刷新事件缓存 + 同步 _attr_state 让历史系统捕获"""
        try:
            data = self.coordinator.data.get("data") if self.coordinator.data else None
            if not data:
                data = self.coordinator.data_manager._data_cache
            if not data:
                return
            self._event_list = self._build_events(data)

            # HA 2026.5+ 历史系统直接读 _attr_state，None 会记为 unavailable
            current = self.event
            new_state = current.summary if current else "空闲"
            if getattr(self, "_attr_state", None) != new_state:
                self._attr_state = new_state
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
