"""Coordinator for Smart Workday - 共享数据管理（Store 持久化 + 日期分析）。

v3.0.0 破坏性重构：
- Store 结构从 3 分类（holidays/studentdays/customdays）合并为 2 分类（legal/custom）
- DayInfo 去掉 is_student_holiday，新增 active_custom: Dict[str, List[str]]
- iter_enabled_items 返回 ("legal"|"custom", item)，custom item 带 category 字段
- 顶层开关 3 → 2：删除 CONF_ENABLED_STUDENT

判定逻辑：
- is_holiday         = 法定假期(非调休)
- is_special_workday = 调休上班日
- is_workday         = is_special_workday OR (非自然周末 AND 非 is_holiday)
- is_weekend         = 自然周末 AND 非 is_special_workday        可与 is_holiday 并列 True
- is_custom_holiday  = 有任一 custom 类别激活（不区分学生/工作/个人/家庭）
- active_custom      = {类别名: [事件名, ...]}，仅含当日活动中的类别

即：以「双休 + 法定」为基准；自定义假期（含学生）是独立的标志位与类别明细。
"""

import logging
import uuid
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt

from .const import (
    DOMAIN,
    CONF_ENABLED_LEGAL,
    CONF_ENABLED_CUSTOM,
    WEEKDAY_NAMES,
    DOMAIN_DISPLAY_NAME,
    MAKEUP_KEYWORD,
    KEY_LEGAL,
    KEY_CUSTOM,
    CALENDAR_KEYS,
    empty_calendar_data,
)

_LOGGER = logging.getLogger(__name__)
# 60 分钟刷新：日历事件按天变化，但需保证 _event_list 缓存及时刷新
# （25h 会让 calendar._event_list 长期停留在昨天的数据 → 跨天后 event property 拿不到当前事件）
SCAN_INTERVAL = timedelta(minutes=60)


@dataclass
class DayInfo:
    """今天的信息数据类 - 布尔标志 + 事件列表 + 活跃自定义类别明细。

    weekday_name / event_names / primary_event 是派生字段，
    由 weekday 和 events 计算得到，不重复存储。

    active_custom: {类别名: [事件名, ...]}
      - 仅包含当日有活跃事件的 custom 类别
      - 用户可通过 attributes.active_custom 精确读到"学生: 寒假"这种信息
    """
    date: str
    weekday: int
    is_workday: bool
    is_holiday: bool
    is_weekend: bool
    is_special_workday: bool
    is_custom_holiday: bool
    active_custom: Dict[str, List[str]] = field(default_factory=dict)
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
            CONF_ENABLED_CUSTOM: True,
        }

    def update_enabled_flags(self, entry_data: Dict[str, Any]):
        """从 entry.data 更新顶层启用开关。缺失字段视为 True（默认启用）。"""
        for key in (CONF_ENABLED_LEGAL, CONF_ENABLED_CUSTOM):
            self._enabled_flags[key] = bool(entry_data.get(key, True))

    async def load_calendar_data(self, force_reload: bool = False) -> Dict:
        """从 Store 加载数据（带 1 分钟缓存）。

        强制补齐 legal/custom 两个键 —— 半写入的 Store 数据可能缺字段，
        不补齐会让 iter_enabled_items 直接 KeyError。
        """
        now = dt.now()

        if not force_reload and self._data_cache and self._last_loaded:
            if (now - self._last_loaded).total_seconds() < 60:
                return self._data_cache

        try:
            data = await self._store.async_load()
            if not data:
                data = empty_calendar_data()
            for key in CALENDAR_KEYS:
                data.setdefault(key, [])

            self._data_cache = data
            self._last_loaded = now
            return data

        except Exception as e:
            _LOGGER.error("加载数据失败: %s", e)
            return empty_calendar_data()

    async def _async_save_sync(self, data: Optional[Dict] = None) -> bool:
        """保存数据到 Store"""
        if data is None:
            data = self._data_cache
        if data is None:
            return False
        try:
            for key in CALENDAR_KEYS:
                data.setdefault(key, []).sort(key=lambda x: x.get("date") or x.get("start", ""))
            await self._store.async_save(data)
            self._data_cache = None
            self._last_loaded = None
            return True
        except Exception as e:
            _LOGGER.error("保存数据失败: %s", e)
            return False

    async def add_entry(self, name: str, start: str, end: Optional[str],
                        category: str = "自定义",
                        description: str = "") -> bool:
        """添加一条自定义假期条目。

        v3.0.0：统一走 custom 分类，通过 category 字段区分类别（学生/工作/个人/家庭/自定义...）。
        """
        data = await self.load_calendar_data(force_reload=True)
        entry: Dict[str, str] = {
            "name": name,
            "uid": str(uuid.uuid4())[:8],
            "category": category or "自定义",
        }
        if end and end != start:
            entry["start"] = start
            entry["end"] = end
        else:
            entry["date"] = start
        if description:
            entry["description"] = description
        data[KEY_CUSTOM].append(entry)
        saved = await self._async_save_sync(data)
        if saved:
            _LOGGER.info("已添加自定义假期: [%s] %s (%s)", category, name, start)
        return saved

    async def delete_entry_by_uid(self, uid: str) -> bool:
        """根据 uid 删除一条假期（合法 + 自定义都覆盖）"""
        data = await self.load_calendar_data(force_reload=True)
        for cat_key in (KEY_LEGAL, KEY_CUSTOM):
            items = data.get(cat_key, [])
            for i, item in enumerate(items):
                if item.get("uid") == uid:
                    items.pop(i)
                    saved = await self._async_save_sync(data)
                    if saved:
                        _LOGGER.info("已删除假期: [%s] %s", cat_key, item.get("name"))
                    return saved
        _LOGGER.warning("未找到 uid=%s 的假期条目", uid)
        return False

    def iter_enabled_items(self, data: Optional[Dict] = None) -> List[Tuple[str, Dict]]:
        """遍历所有启用的条目，返回 (kind, item) 元组列表。

        v3.0.0：
        - kind 只有两种：'legal' / 'custom'
        - custom 条目的具体类别通过 item["category"] 字段区分（学生/工作/...）
        - 应用顶层开关 + 条目级 enabled（custom 条目支持）双重过滤
        """
        if data is None:
            data = self._data_cache or empty_calendar_data()

        results: List[Tuple[str, Dict]] = []

        # 法定假期（顶层开关控制）
        if self._enabled_flags[CONF_ENABLED_LEGAL]:
            for item in data.get(KEY_LEGAL, []):
                results.append(("legal", item))

        # 自定义假期（顶层开关 + 条目级 enabled 双重控制）
        if self._enabled_flags[CONF_ENABLED_CUSTOM]:
            for item in data.get(KEY_CUSTOM, []):
                if item.get("enabled", True):
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
        """获取指定日期的所有事件（顶层开关关闭的分类被跳过）。

        返回结构：
        - legal 条目：{"name", "type": "holiday"|"special"}
        - custom 条目：{"name", "type": "custom", "category": "学生"|"工作"|...}
        """
        if check_date is None:
            check_date = dt.now().date()
        if data is None:
            data = self._data_cache or empty_calendar_data()

        events: List[Dict] = []
        for kind, item in self.iter_enabled_items(data):
            if not self._item_matches_date(item, check_date):
                continue
            if kind == "legal":
                is_makeup = MAKEUP_KEYWORD in item["name"]
                events.append({
                    "name": item["name"],
                    "type": "special" if is_makeup else "holiday",
                })
            else:  # custom
                events.append({
                    "name": item["name"],
                    "type": "custom",
                    "category": item.get("category", "自定义"),
                })
        return events

    def analyze_day(self, today: date, events: List[Dict]) -> DayInfo:
        """分析一天的状态：

        - 以「双休 + 法定假期」为主：工作日/节假日/周末由这三个决定
        - 自定义假期为独立标志位，通过 active_custom 暴露每个类别的明细
        - 调休上班日（special）优先级最高：即使周末也算工作日
        - 法定假期 + 周六同天：is_holiday=True 且 is_weekend=True（并列）
        """
        flags = {"holiday": False, "special": False, "custom": False}
        active_custom: Dict[str, List[str]] = {}

        for e in events:
            etype = e.get("type")
            if etype == "holiday":
                flags["holiday"] = True
            elif etype == "special":
                flags["special"] = True
            elif etype == "custom":
                flags["custom"] = True
                category = e.get("category", "自定义")
                active_custom.setdefault(category, []).append(e["name"])

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

        # 自定义假期：任一类别激活即为 True
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
            is_custom_holiday=is_custom_holiday,
            active_custom=active_custom,
            day_type=day_type,
            events=events,
        )

    def get_upcoming_days(self, today: date, days: int = 7,
                          data: Optional[Dict] = None) -> List[Dict]:
        """获取未来几天信息"""
        if data is None:
            data = self._data_cache or empty_calendar_data()
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


class SmartWorkdayCoordinator(DataUpdateCoordinator):
    """协调器 - 管理数据更新。

    data 结构（v3.0.0）：
    {
        "day_info": DayInfo,       # 今天完整信息（属性直接访问）
        "upcoming": List[Dict],    # 未来几天事件
        "data": Dict,              # 原始 Store 数据（供 calendar 构建事件复用）
    }
    """

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
        """更新数据 - 一次性算出今天信息 + 未来事件 + 原始缓存"""
        try:
            today = dt.now().date()
            data = await self.data_manager.load_calendar_data()
            events = self.data_manager.get_today_events(today, data)
            day_info = self.data_manager.analyze_day(today, events)
            upcoming = self.data_manager.get_upcoming_days(today, days=7, data=data)

            return {
                "day_info": day_info,
                "upcoming": upcoming,
                "data": data,
            }

        except Exception as err:
            _LOGGER.error("更新数据失败: %s", err)
            raise UpdateFailed(f"更新失败: {err}")
