"""Coordinator for Smart Workday - 共享数据管理（Store 持久化 + 3 态判定）"""

import logging
import uuid
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt

from .const import (
    DOMAIN,
    HolidayMode,
    ATTR_IS_WORKDAY,
    ATTR_IS_HOLIDAY,
    ATTR_IS_WEEKEND,
    ATTR_IS_SPECIAL_WORKDAY,
    ATTR_IS_STUDENT_HOLIDAY,
    CONF_ENABLED_LEGAL,
    CONF_ENABLED_STUDENT,
    CONF_ENABLED_CUSTOM,
    WEEKDAY_NAMES,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=60)
STORAGE_VERSION = 1


@dataclass
class DayInfo:
    """今天的信息数据类 - 全部为布尔标志，详细信息在属性中"""
    date: str
    weekday: int
    weekday_name: str
    is_workday: bool
    is_holiday: bool
    is_weekend: bool
    is_special_workday: bool
    is_student_holiday: bool
    mode: HolidayMode
    mode_name: str
    events: List[Dict] = field(default_factory=list)
    event_names: List[str] = field(default_factory=list)
    primary_event: str = ""
    upcoming_days: List[Dict] = field(default_factory=list)


class SmartWorkdayDataManager:
    """数据管理器 - Store JSON 持久化 + 日期分析"""

    def __init__(self, hass: HomeAssistant, store: Store):
        self.hass = hass
        self._store = store
        self._data_cache: Optional[Dict] = None
        self._last_loaded = None
        self._holiday_mode = HolidayMode.STANDARD
        self._enabled_flags: Dict[str, bool] = {
            CONF_ENABLED_LEGAL: True,
            CONF_ENABLED_STUDENT: True,
            CONF_ENABLED_CUSTOM: True,
        }

    def update_holiday_mode(self, mode: HolidayMode):
        self._holiday_mode = mode

    def update_enabled_flags(self, entry_data: Dict[str, Any]):
        """从 entry.data 更新顶层启用开关（向后兼容：未设置默认 True）"""
        for key in (CONF_ENABLED_LEGAL, CONF_ENABLED_STUDENT, CONF_ENABLED_CUSTOM):
            self._enabled_flags[key] = bool(entry_data.get(key, True))

    async def load_calendar_data(self, force_reload: bool = False) -> Dict:
        """从 Store 加载数据（带 1 分钟缓存）"""
        now = dt.now()

        if not force_reload and self._data_cache and self._last_loaded:
            if (now - self._last_loaded).total_seconds() < 60:
                return self._data_cache

        try:
            data = await self._store.async_load()
            if data is None or not isinstance(data, dict):
                data = {}

            data.setdefault("holidays", [])
            data.setdefault("customdays", [])
            data.setdefault("studentdays", [])

            # 补全 uid（向后兼容旧数据）
            need_save = False
            for cat in ("holidays", "customdays", "studentdays"):
                if not isinstance(data[cat], list):
                    data[cat] = []
                for item in data[cat]:
                    if not isinstance(item, dict):
                        continue
                    if "uid" not in item:
                        item["uid"] = str(uuid.uuid4())[:8]
                        need_save = True

            self._data_cache = data
            self._last_loaded = now
            if need_save:
                await self._async_save_sync(data)

            return data

        except Exception as e:
            _LOGGER.error("加载数据失败: %s", e)
            return {"holidays": [], "customdays": [], "studentdays": []}

    async def _async_save_sync(self, data: Optional[Dict] = None) -> bool:
        """保存数据到 Store"""
        if data is None:
            data = self._data_cache
        if data is None:
            return False
        try:
            for key in ("holidays", "customdays", "studentdays"):
                data[key].sort(key=lambda x: x.get("date") or x.get("start", ""))
            await self._store.async_save(data)
            self._data_cache = None
            self._last_loaded = None
            return True
        except Exception as e:
            _LOGGER.error("保存数据失败: %s", e)
            return False

    async def add_entry(self, category: str, name: str, start: str, end: Optional[str],
                        description: str = "") -> bool:
        """添加一条假期条目"""
        data = await self.load_calendar_data(force_reload=True)
        entry: Dict[str, str] = {"name": name, "uid": str(uuid.uuid4())[:8]}
        if end and end != start:
            entry["start"] = start
            entry["end"] = end
        else:
            entry["date"] = start
        if description:
            entry["description"] = description
        data.setdefault(category, []).append(entry)
        saved = await self._async_save_sync(data)
        if saved:
            _LOGGER.info("已添加假期: [%s] %s (%s)", category, name, start)
        return saved

    async def delete_entry_by_uid(self, uid: str) -> bool:
        """根据 uid 删除一条假期"""
        data = await self.load_calendar_data(force_reload=True)
        for cat in ("holidays", "customdays", "studentdays"):
            items = data.get(cat, [])
            for i, item in enumerate(items):
                if isinstance(item, dict) and item.get("uid") == uid:
                    items.pop(i)
                    saved = await self._async_save_sync(data)
                    if saved:
                        _LOGGER.info("已删除假期: [%s] %s", cat, item.get("name", "?"))
                    return saved
        _LOGGER.warning("未找到 uid=%s 的假期条目", uid)
        return False

    def get_today_events(self, check_date: Optional[date] = None,
                         data: Optional[Dict] = None) -> List[Dict]:
        """获取指定日期的所有事件（顶层开关关闭的分类被跳过）"""
        if check_date is None:
            check_date = dt.now().date()
        if data is None:
            data = self._data_cache or {}

        events = []

        def is_match(date_obj: date, item: Dict) -> bool:
            try:
                if "date" in item:
                    return item["date"] == date_obj.isoformat()
                elif "start" in item and "end" in item:
                    start = datetime.strptime(item["start"], "%Y-%m-%d").date()
                    end = datetime.strptime(item["end"], "%Y-%m-%d").date()
                    return start <= date_obj <= end
            except Exception as e:
                _LOGGER.debug("日期匹配错误: %s", e)
            return False

        # 法定节假日（顶层开关控制）
        if self._enabled_flags.get(CONF_ENABLED_LEGAL, True):
            for item in data.get("holidays", []):
                if is_match(check_date, item):
                    events.append({
                        "name": item.get("name", "节假日"),
                        "type": "holiday" if "调休" not in item.get("name", "") else "special",
                    })

        # 自定义假期（顶层开关控制）
        if self._enabled_flags.get(CONF_ENABLED_CUSTOM, True):
            for item in data.get("customdays", []):
                if is_match(check_date, item):
                    events.append({
                        "name": item.get("name", "自定义假期"),
                        "type": "custom",
                    })

        # 学生假期（顶层开关 + 条目 enabled 双重控制）
        if self._enabled_flags.get(CONF_ENABLED_STUDENT, True):
            for item in data.get("studentdays", []):
                if not item.get("enabled", True):
                    continue
                if is_match(check_date, item):
                    events.append({
                        "name": item.get("name", "学生假期"),
                        "type": "student",
                    })

        return events

    def analyze_day(self, today: date, events: List[Dict]) -> DayInfo:
        """分析一天的状态 - 用户规则（v2.5.0）：

        - is_workday = True ⟺ 调休上班 OR (非自然周末 AND 非节假日)
        - 节假日 = 法定节假日(非调休) OR 自定义假期
        - 学生假期独立，不影响工作日判定
        """
        flags = {"holiday": False, "special": False, "custom": False, "student": False}
        event_names = []

        for e in events:
            event_names.append(e["name"])
            if e["type"] == "holiday":
                flags["holiday"] = True
            elif e["type"] == "special":
                flags["special"] = True
            elif e["type"] == "custom":
                flags["custom"] = True
            elif e["type"] == "student":
                flags["student"] = True

        # 自然周末（周六/周日）
        natural_weekend = today.weekday() >= 5

        # 节假日 = 法定节假日(非调休) OR 自定义假期
        is_holiday = flags["holiday"] or flags["custom"]

        # 调休上班日优先级最高：即使周末也算工作日
        is_special_workday = flags["special"]

        # 工作日 = 调休上班 OR (非自然周末 AND 非节假日)
        is_workday = is_special_workday or (not natural_weekend and not is_holiday)

        # 双休日 = 自然周末 且 非调休上班
        is_weekend = natural_weekend and not is_special_workday

        return DayInfo(
            date=today.isoformat(),
            weekday=today.weekday(),
            weekday_name=WEEKDAY_NAMES[today.weekday()],
            is_workday=is_workday,
            is_holiday=is_holiday,
            is_weekend=is_weekend,
            is_special_workday=is_special_workday,
            is_student_holiday=flags["student"],
            mode=self._holiday_mode,
            mode_name=self._holiday_mode.display_name,
            events=events,
            event_names=list(dict.fromkeys(event_names)),
            primary_event=event_names[0] if event_names else "",
        )

    def get_upcoming_days(self, today: date, days: int = 7,
                          data: Optional[Dict] = None) -> List[Dict]:
        """获取未来几天信息"""
        if data is None:
            data = self._data_cache or {}
        upcoming = []
        for i in range(1, days + 1):
            future = today + timedelta(days=i)
            events = self.get_today_events(future, data)
            if events:
                upcoming.append({
                    "date": future.isoformat(),
                    "events": [e["name"] for e in events],
                })
        return upcoming

    async def get_calendar_events(self) -> Dict:
        """获取所有日历事件（用于日历实体）"""
        return await self.load_calendar_data(force_reload=True)


class SmartWorkdayCoordinator(DataUpdateCoordinator):
    """协调器 - 管理数据更新"""

    def __init__(self, hass: HomeAssistant, entry_id: str, data_manager: SmartWorkdayDataManager):
        super().__init__(
            hass,
            _LOGGER,
            name=f"Smart Workday {entry_id}",
            update_interval=SCAN_INTERVAL,
        )
        self.entry_id = entry_id
        self.data_manager = data_manager

    async def _async_update_data(self) -> Dict[str, Any]:
        """更新数据"""
        try:
            today = dt.now().date()

            # 加载数据
            data = await self.data_manager.load_calendar_data()

            # 获取当天事件
            events = self.data_manager.get_today_events(today, data)

            # 分析当天
            day_info = self.data_manager.analyze_day(today, events)

            # 获取未来事件
            upcoming = self.data_manager.get_upcoming_days(today, days=7, data=data)

            return {
                "date": day_info.date,
                "weekday": day_info.weekday,
                "weekday_name": day_info.weekday_name,
                ATTR_IS_WORKDAY: day_info.is_workday,
                ATTR_IS_HOLIDAY: day_info.is_holiday,
                ATTR_IS_WEEKEND: day_info.is_weekend,
                ATTR_IS_SPECIAL_WORKDAY: day_info.is_special_workday,
                ATTR_IS_STUDENT_HOLIDAY: day_info.is_student_holiday,
                "mode": day_info.mode.value,
                "mode_name": day_info.mode_name,
                "events": day_info.events,
                "event_names": day_info.event_names,
                "primary_event": day_info.primary_event,
                "upcoming": upcoming,
            }

        except Exception as err:
            _LOGGER.error("更新数据失败: %s", err)
            raise UpdateFailed(f"更新失败: {err}")