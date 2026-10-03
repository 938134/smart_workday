"""Calendar platform for Smart Workday - 单日历合并显示所有分类事件。

- 显示所有分类事件（法定/学生/自定义），description 标注来源
- 仅支持 DELETE_EVENT（录入走 OptionsFlow 表单）
- 法定假期自动导入（国务院通知），不支持手动添加
"""

import logging
from datetime import datetime, timedelta
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
    DEFAULT_NAME,
    DOMAIN_DISPLAY_NAME,
    CALENDAR_MODEL,
    CALENDAR_ENTITY_NAME,
    CALENDAR_UNIQUE_SUFFIX,
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


class SmartWorkdayCalendar(CoordinatorEntity, CalendarEntity):
    """单日历实体 - 显示所有分类事件，description 标注来源。"""

    _attr_has_entity_name = True
    # 仅支持删除（录入走 OptionsFlow 表单）
    _attr_supported_features = CalendarEntityFeature.DELETE_EVENT

    def __init__(self, coordinator: SmartWorkdayCoordinator, device_info: DeviceInfo):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}{CALENDAR_UNIQUE_SUFFIX}"
        self._attr_name = CALENDAR_ENTITY_NAME
        self._attr_device_info = device_info
        self._attr_sw_version = VERSION
        self._attr_icon = "mdi:calendar-month"
        self._event_list: List[CalendarEvent] = []

    # ---------- 时区 ----------

    def _get_tz(self) -> datetime.tzinfo:
        """获取 HA 系统时区"""
        try:
            return ZoneInfo(self.hass.config.time_zone)
        except Exception:
            return ZoneInfo("UTC")

    # ---------- 事件构建 ----------

    @property
    def available(self) -> bool:
        """显式返回 True，避免 coordinator 更新失败时日历整块变 unavailable"""
        return True

    def _create_event(self, start_date, end_date, name: str, uid: str = "",
                      description: str = "",
                      tz: Optional[datetime.tzinfo] = None) -> Optional[CalendarEvent]:
        """创建日历事件（start_date 缺失时返回 None，调用方跳过）"""
        if not start_date:
            _LOGGER.warning("跳过事件 '%s'：start_date 为空", name)
            return None

        # 解析开始日期
        if isinstance(start_date, str):
            try:
                start = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError) as e:
                _LOGGER.warning("跳过事件 '%s'：开始日期解析失败 %r (%s)", name, start_date, e)
                return None
        elif hasattr(start_date, "year"):
            start = start_date
        else:
            _LOGGER.warning("跳过事件 '%s'：开始日期类型异常 %r", name, start_date)
            return None

        # 解析结束日期（单天事件 end_date 可能为 None 或等于 start）
        if end_date is None or end_date == start_date:
            end = start
        else:
            if isinstance(end_date, str):
                try:
                    end = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
                except (ValueError, TypeError) as e:
                    _LOGGER.warning("事件 '%s'：结束日期解析失败 %r (%s)，按单日处理", name, end_date, e)
                    end = start
            elif hasattr(end_date, "year"):
                end = end_date
            else:
                end = start

        event_start = datetime.combine(start, datetime.min.time())
        event_end = datetime.combine(end + timedelta(days=1), datetime.min.time())

        # 补齐时区
        if tz is None:
            tz = self._get_tz()
        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=tz)
        if event_end.tzinfo is None:
            event_end = event_end.replace(tzinfo=tz)

        return CalendarEvent(
            start=event_start,
            end=event_end,
            summary=name,
            description=description,
            uid=uid,
        )

    async def _generate_events(self) -> List[CalendarEvent]:
        """生成所有分类的日历事件（顶层开关关闭的分类不显示）"""
        events = []
        try:
            data = await self.coordinator.data_manager.get_calendar_events()
        except Exception as e:
            _LOGGER.error("获取日历数据失败: %s", e)
            data = {"holidays": [], "studentdays": [], "customdays": []}
        tz = self._get_tz()
        flags = getattr(self.coordinator.data_manager, "_enabled_flags", {})
        _LOGGER.info("日历生成开始: flags=%s 数据总量 holidays=%d studentdays=%d customdays=%d",
                     flags,
                     len(data.get("holidays", [])),
                     len(data.get("studentdays", [])),
                     len(data.get("customdays", [])))

        # 法定假期（顶层开关控制）
        if flags.get(CONF_ENABLED_LEGAL, True):
            for item in data.get("holidays", []):
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "法定假期")
                desc = EVENT_SOURCE_MAKEUP if MAKEUP_KEYWORD in name else EVENT_SOURCE_LEGAL
                ev = self._create_event(
                    item.get("date") or item.get("start"),
                    item.get("date") or item.get("end"),
                    name, item.get("uid", ""), desc, tz,
                )
                if ev:
                    events.append(ev)

        # 学生假期（顶层开关 + 条目 enabled 双重控制）
        if flags.get(CONF_ENABLED_STUDENT, True):
            for item in data.get("studentdays", []):
                if not isinstance(item, dict):
                    continue
                if not item.get("enabled", True):
                    continue
                ev = self._create_event(
                    item.get("date") or item.get("start"),
                    item.get("date") or item.get("end"),
                    item.get("name", "学生假期"),
                    item.get("uid", ""),
                    EVENT_SOURCE_STUDENT,
                    tz,
                )
                if ev:
                    events.append(ev)

        # 自定义假期（顶层开关控制）
        if flags.get(CONF_ENABLED_CUSTOM, True):
            for item in data.get("customdays", []):
                if not isinstance(item, dict):
                    continue
                ev = self._create_event(
                    item.get("date") or item.get("start"),
                    item.get("date") or item.get("end"),
                    item.get("name", "自定义假期"),
                    item.get("uid", ""),
                    EVENT_SOURCE_CUSTOM,
                    tz,
                )
                if ev:
                    events.append(ev)

        _LOGGER.info("日历生成完成: 共 %d 个事件", len(events))
        return events

    async def async_get_events(self, hass, start_date, end_date) -> List[CalendarEvent]:
        """获取时间段内的事件"""
        tz = self._get_tz()
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=tz)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=tz)

        try:
            all_events = await self._generate_events()
            filtered = [
                e for e in all_events
                if e.start <= end_date and e.end >= start_date
            ]
            _LOGGER.debug("async_get_events [%s ~ %s]: 全部 %d 条, 过滤后 %d 条",
                          start_date.date(), end_date.date(), len(all_events), len(filtered))
            return filtered
        except Exception as e:
            _LOGGER.error("async_get_events 失败: %s", e, exc_info=True)
            return []

    @property
    def event(self) -> Optional[CalendarEvent]:
        """返回下一个即将发生的事件。

        ⚠️ CalendarEntity 不会主动 poll，_event_list 可能为空。
        这里做兜底：如果 _event_list 为空，直接同步查一次缓存数据。
        """
        events = self._event_list
        if not events:
            try:
                dm = self.coordinator.data_manager
                data = getattr(dm, "_data_cache", None)
                if data:
                    tz = self._get_tz()
                    src_map = {
                        "holidays": EVENT_SOURCE_LEGAL,
                        "studentdays": EVENT_SOURCE_STUDENT,
                        "customdays": EVENT_SOURCE_CUSTOM,
                    }
                    flag_map = {
                        "holidays": CONF_ENABLED_LEGAL,
                        "studentdays": CONF_ENABLED_STUDENT,
                        "customdays": CONF_ENABLED_CUSTOM,
                    }
                    tmp_events = []
                    for cat, default_src in src_map.items():
                        if not dm._enabled_flags.get(flag_map[cat], True):
                            continue
                        for item in data.get(cat, []):
                            if not isinstance(item, dict):
                                continue
                            if cat == "studentdays" and not item.get("enabled", True):
                                continue
                            name = item.get("name", "")
                            src = EVENT_SOURCE_MAKEUP if (cat == "holidays" and MAKEUP_KEYWORD in name) else default_src
                            ev = self._create_event(
                                item.get("date") or item.get("start"),
                                item.get("date") or item.get("end"),
                                name, item.get("uid", ""), src, tz,
                            )
                            if ev:
                                tmp_events.append(ev)
                    if tmp_events:
                        self._event_list = tmp_events
                        events = tmp_events
            except Exception as e:
                _LOGGER.debug("event 属性兜底查询失败: %s", e)

        if not events:
            return None
        try:
            now = dt.now()
            # 优先级 1：今天正在进行中的事件（start <= now < end）
            ongoing = [e for e in events if e.start <= now < e.end]
            if ongoing:
                return min(ongoing, key=lambda e: e.start)
            # 优先级 2：未来最近的事件
            future = [e for e in events if e.start > now]
            if future:
                return min(future, key=lambda e: e.start)
            # 优先级 3：今天内的事件（同日 start/end，可能刚过 now 或跨午夜）
            today_events = [
                e for e in events
                if e.start.date() == now.date() or e.end.date() == now.date()
            ]
            if today_events:
                return min(today_events, key=lambda e: e.start)
            return None
        except Exception as e:
            _LOGGER.error("event 属性计算失败: %s", e)
            return None

    async def async_update(self) -> None:
        """更新日历事件（由 HA 按需调用；CalendarEntity 通常不主动 poll）"""
        try:
            self._event_list = await self._generate_events()
            _LOGGER.debug("async_update 完成，共 %d 个事件", len(self._event_list))
        except Exception as e:
            _LOGGER.error("更新日历失败: %s", e)

    # ---------- 日历 UI 删除支持 ----------

    async def async_delete_event(self, uid: str, **kwargs) -> None:
        """通过日历 UI 删除事件（遍历所有分类查找 uid）"""
        if not uid:
            raise ValueError("删除事件需要 uid")

        dm = self.coordinator.data_manager
        # 先检查 uid 是否存在
        data = await dm.get_calendar_events()
        found = False
        for cat in ("holidays", "studentdays", "customdays"):
            items = data.get(cat, [])
            if any(isinstance(item, dict) and item.get("uid") == uid for item in items):
                found = True
                break
        if not found:
            raise ValueError(f"未找到 uid={uid} 的事件")

        deleted = await dm.delete_entry_by_uid(uid)
        if not deleted:
            raise ValueError(f"未找到 uid={uid} 的假期条目")

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
        name=entry.data.get("name", DEFAULT_NAME),
        manufacturer=DOMAIN_DISPLAY_NAME,
        model=CALENDAR_MODEL,
        sw_version=VERSION,
    )

    async_add_entities([SmartWorkdayCalendar(coordinator, device_info)])
    _LOGGER.info("已添加 %s 实体", CALENDAR_ENTITY_NAME)
