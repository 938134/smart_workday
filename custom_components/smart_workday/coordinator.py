"""Coordinator for Smart Workday - 共享数据管理（Store 持久化 + 日期分析）。

判定逻辑（v2.6.0，简化）：
- is_holiday         = 法定假期(非调休)                       只算法定，自定义不算
- is_special_workday = 调休上班日
- is_workday         = is_special_workday OR (非自然周末 AND 非 is_holiday)
- is_weekend         = 自然周末 AND 非 is_special_workday        可与 is_holiday 并列 True
- is_student_holiday = 学生假期（独立 boolean，不影响工作日）
- is_custom_holiday  = 自定义假期（独立 boolean，不影响工作日）

即：以「双休 + 法定」为基准；学生假期和自定义假期是独立的标志位。
"""

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
    STORAGE_VERSION,
    ATTR_IS_WORKDAY,
    ATTR_IS_HOLIDAY,
    ATTR_IS_WEEKEND,
    ATTR_IS_SPECIAL_WORKDAY,
    ATTR_IS_STUDENT_HOLIDAY,
    ATTR_IS_CUSTOM_HOLIDAY,
    ATTR_DAY_TYPE,
    CONF_ENABLED_LEGAL,
    CONF_ENABLED_STUDENT,
    CONF_ENABLED_CUSTOM,
    WEEKDAY_NAMES,
    DOMAIN_DISPLAY_NAME,
    MAKEUP_KEYWORD,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=60)


@dataclass
class DayInfo:
    """今天的信息数据类 - 布尔标志 + 事件列表。

    weekday_name / event_names / primary_event 是派生字段，
    由 weekday 和 events 计算得到，不重复存储。
    """
    date: str
    weekday: int
    is_workday: bool
    is_holiday: bool
    is_weekend: bool
    is_special_workday: bool
    is_student_holiday: bool
    is_custom_holiday: bool
    day_type: str = ""
    events: List[Dict] = field(default_factory=list)

    @property
    def weekday_name(self) -> str:
        return WEEKDAY_NAMES[self.weekday]

    @property
    def event_names(self) -> List[str]:
        return [e["name"] for e in self.events]

    @property
    def primary_event(self) -> str:
        return self.events[0]["name"] if self.events else ""


class SmartWorkdayDataManager:
    """数据管理器 - Store JSON 持久化 + 日期分析"""

    def __init__(self, hass: HomeAssistant, store: Store):
        self.hass = hass
        self._store = store
        self._data_cache: Optional[Dict] = None
        self._last_loaded = None
        self._enabled_flags: Dict[str, bool] = {
            CONF_ENABLED_LEGAL: True,
            CONF_ENABLED_STUDENT: True,
            CONF_ENABLED_CUSTOM: True,
        }

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

            # 清理无效条目 + 补全 uid（向后兼容旧数据）
            need_save = False
            for cat in ("holidays", "customdays", "studentdays"):
                if not isinstance(data[cat], list):
                    data[cat] = []
                # 移除非 dict 项（历史 bug 或手工编辑导致的脏数据）
                cleaned = [item for item in data[cat] if isinstance(item, dict)]
                removed = len(data[cat]) - len(cleaned)
                if removed > 0:
                    _LOGGER.warning("清理 %s 中 %d 条无效数据", cat, removed)
                    data[cat] = cleaned
                    need_save = True
                for item in cleaned:
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

    def iter_enabled_items(self, data: Optional[Dict] = None) -> List[tuple]:
        """遍历所有启用的分类条目，返回 (category, item) 元组列表。

        - category 取值：'holiday'（含调休） / 'student' / 'custom'
        - 应用顶层开关 + student 条目级 enabled 双重过滤
        - 统一去重：只返回 dict 类型、字段完整的条目

        供 get_today_events（判定 flags）与 calendar 事件构建（构造 CalendarEvent）复用。
        """
        if data is None:
            data = self._data_cache or {}

        results: List[tuple] = []

        # 法定假期（顶层开关控制）
        if self._enabled_flags.get(CONF_ENABLED_LEGAL, True):
            for item in data.get("holidays", []):
                if isinstance(item, dict):
                    results.append(("holiday", item))

        # 学生假期（顶层开关 + 条目 enabled 双重控制）
        if self._enabled_flags.get(CONF_ENABLED_STUDENT, True):
            for item in data.get("studentdays", []):
                if isinstance(item, dict) and item.get("enabled", True):
                    results.append(("student", item))

        # 自定义假期（顶层开关控制）
        if self._enabled_flags.get(CONF_ENABLED_CUSTOM, True):
            for item in data.get("customdays", []):
                if isinstance(item, dict):
                    results.append(("custom", item))

        return results

    @staticmethod
    def _item_matches_date(item: Dict, check_date: date) -> bool:
        """判断条目是否覆盖 check_date（支持 date 单日型与 start/end 范围型）"""
        try:
            if "date" in item:
                return item["date"] == check_date.isoformat()
            if "start" in item and "end" in item:
                start = datetime.strptime(item["start"], "%Y-%m-%d").date()
                end = datetime.strptime(item["end"], "%Y-%m-%d").date()
                return start <= check_date <= end
        except Exception as e:
            _LOGGER.debug("日期匹配错误: %s", e)
        return False

    def get_today_events(self, check_date: Optional[date] = None,
                         data: Optional[Dict] = None) -> List[Dict]:
        """获取指定日期的所有事件（顶层开关关闭的分类被跳过）"""
        if check_date is None:
            check_date = dt.now().date()
        if data is None:
            data = self._data_cache or {}

        events: List[Dict] = []
        for category, item in self.iter_enabled_items(data):
            if not self._item_matches_date(item, check_date):
                continue
            # 法定假期中，名称含"调休"视为调休上班（special）
            if category == "holiday":
                is_makeup = MAKEUP_KEYWORD in item.get("name", "")
                events.append({
                    "name": item.get("name", "节假日"),
                    "type": "special" if is_makeup else "holiday",
                })
            elif category == "student":
                events.append({
                    "name": item.get("name", "学生假期"),
                    "type": "student",
                })
            else:  # custom
                events.append({
                    "name": item.get("name", "自定义假期"),
                    "type": "custom",
                })
        return events

    def analyze_day(self, today: date, events: List[Dict]) -> DayInfo:
        """分析一天的状态 - v2.6.0 简化规则：

        - 以「双休 + 法定假期」为主：工作日/节假日/周末由这三个决定
        - 学生假期、自定义假期为独立 boolean 标志位，不影响工作日判定
        - 调休上班日（special）优先级最高：即使周末也算工作日
        - 法定假期 + 周六同天：is_holiday=True 且 is_weekend=True（并列）
        """
        flags = {"holiday": False, "special": False, "custom": False, "student": False}

        for e in events:
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

        # 节假日：只算法定假期（非调休）；自定义假期不影响这里
        is_holiday = flags["holiday"]

        # 调休上班日优先级最高：即使周末也算工作日
        is_special_workday = flags["special"]

        # 工作日 = 调休上班 OR (非自然周末 AND 非法定假期)
        is_workday = is_special_workday or (not natural_weekend and not is_holiday)

        # 双休日 = 自然周末 且 非调休上班（可与 is_holiday 并列）
        is_weekend = natural_weekend and not is_special_workday

        # 学生假期 / 自定义假期：独立标志位
        is_student_holiday = flags["student"]
        is_custom_holiday = flags["custom"]

        # day_type：主要身份描述（优先级：调休上班 > 法定假期 > 周末 > 工作日）
        if is_special_workday:
            day_type = "调休上班"
        elif is_holiday:
            day_type = "法定假期"
        elif natural_weekend:
            day_type = "周末"
        else:
            day_type = "工作日"

        return DayInfo(
            date=today.isoformat(),
            weekday=today.weekday(),
            is_workday=is_workday,
            is_holiday=is_holiday,
            is_weekend=is_weekend,
            is_special_workday=is_special_workday,
            is_student_holiday=is_student_holiday,
            is_custom_holiday=is_custom_holiday,
            day_type=day_type,
            events=events,
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
            name=f"{DOMAIN_DISPLAY_NAME} {entry_id}",
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
                ATTR_IS_CUSTOM_HOLIDAY: day_info.is_custom_holiday,
                ATTR_DAY_TYPE: day_info.day_type,
                "events": day_info.events,
                "event_names": day_info.event_names,
                "primary_event": day_info.primary_event,
                "upcoming": upcoming,
            }

        except Exception as err:
            _LOGGER.error("更新数据失败: %s", err)
            raise UpdateFailed(f"更新失败: {err}")
