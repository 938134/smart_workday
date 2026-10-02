"""Constants for Smart Workday."""

from enum import Enum
from typing import Any, Final, Dict, List

DOMAIN: Final = "smart_workday"
DEFAULT_NAME: Final = "智能工作日"


class HolidayMode(str, Enum):
    """假期模式（顶层开关：法定/自定义是否算放假）"""
    STANDARD = "standard"  # 标准模式：法定节假日 + 自定义
    CUSTOM = "custom"      # 自由模式：仅自定义

    @property
    def display_name(self) -> str:
        return _MODE_NAMES[self]

    @property
    def description(self) -> str:
        return _MODE_DESCRIPTIONS[self]

    @property
    def icon(self) -> str:
        return _MODE_ICONS[self]


# 模式名称/描述/图标映射
_MODE_NAMES: Dict[HolidayMode, str] = {
    HolidayMode.STANDARD: "标准模式",
    HolidayMode.CUSTOM: "自由模式",
}

_MODE_DESCRIPTIONS: Dict[HolidayMode, str] = {
    HolidayMode.STANDARD: "法定节假日 + 自定义假期都算放假",
    HolidayMode.CUSTOM: "只有自定义假期算放假，法定仅参考",
}

_MODE_ICONS: Dict[HolidayMode, str] = {
    HolidayMode.STANDARD: "📅",
    HolidayMode.CUSTOM: "🌟",
}


# ---------- 顶层启用开关（entry.data 键名） ----------
CONF_ENABLED_LEGAL: Final = "enabled_legal"
CONF_ENABLED_STUDENT: Final = "enabled_student"
CONF_ENABLED_CUSTOM: Final = "enabled_custom"
CONF_HOLIDAY_MODE: Final = "holiday_mode"
CONF_NAME: Final = "name"

# 三个总开关 → 数据分类键
ENABLED_TO_CATEGORY: Final = {
    CONF_ENABLED_LEGAL: "holidays",
    CONF_ENABLED_STUDENT: "studentdays",
    CONF_ENABLED_CUSTOM: "customdays",
}

# 三个总开关 → 中文标签
ENABLED_LABELS: Final = {
    CONF_ENABLED_LEGAL: "📅 法定节假日",
    CONF_ENABLED_STUDENT: "🎓 学生假期",
    CONF_ENABLED_CUSTOM: "⭐ 自定义假期",
}


# ---------- 属性常量（供二进制传感器属性读取） ----------
ATTR_IS_WORKDAY: Final = "is_workday"
ATTR_IS_HOLIDAY: Final = "is_holiday"
ATTR_IS_WEEKEND: Final = "is_weekend"
ATTR_IS_SPECIAL_WORKDAY: Final = "is_special_workday"
ATTR_IS_STUDENT_HOLIDAY: Final = "is_student_holiday"


# ---------- 日历事件类型标记（description 前缀，用于单日历 UI 区分来源） ----------
EVENT_SOURCE_LEGAL: Final = "📅 法定节假日"
EVENT_SOURCE_STUDENT: Final = "🎓 学生假期"
EVENT_SOURCE_CUSTOM: Final = "⭐ 自定义假期"
EVENT_SOURCE_MAKEUP: Final = "💼 调休上班日"

# description 前缀 → 数据分类键（用于从单日历删除事件时推断分类）
SOURCE_TO_CATEGORY: Final = {
    EVENT_SOURCE_LEGAL: "holidays",
    EVENT_SOURCE_MAKEUP: "holidays",
    EVENT_SOURCE_STUDENT: "studentdays",
    EVENT_SOURCE_CUSTOM: "customdays",
}


# ---------- 学生假期类型（5 项固定类型） ----------
class StudentHolidayType(str, Enum):
    """学生假期类型 - UI 上 5 个 checkbox 对应"""
    WINTER = "winter"      # 寒假
    SUMMER = "summer"      # 暑假
    SPRING = "spring"      # 春假
    AUTUMN = "autumn"      # 秋假
    CHILDREN = "children"  # 儿童节

    @property
    def display_name(self) -> str:
        return _STUDENT_HOLIDAY_NAMES[self]

    @property
    def is_range(self) -> bool:
        """是否为日期范围（儿童节是单日）"""
        return self != StudentHolidayType.CHILDREN


_STUDENT_HOLIDAY_NAMES: Dict[StudentHolidayType, str] = {
    StudentHolidayType.WINTER: "寒假",
    StudentHolidayType.SUMMER: "暑假",
    StudentHolidayType.SPRING: "春假",
    StudentHolidayType.AUTUMN: "秋假",
    StudentHolidayType.CHILDREN: "儿童节",
}

# 学生假期默认配置（首次导入时的模板）
STUDENT_HOLIDAY_DEFAULTS: Dict[StudentHolidayType, Dict[str, Any]] = {
    StudentHolidayType.WINTER:   {"start": "2026-01-25", "end": "2026-02-21", "enabled": True},
    StudentHolidayType.SUMMER:   {"start": "2026-07-01", "end": "2026-08-31", "enabled": True},
    StudentHolidayType.SPRING:   {"start": "", "end": "", "enabled": False},
    StudentHolidayType.AUTUMN:   {"start": "", "end": "", "enabled": False},
    StudentHolidayType.CHILDREN: {"date": "2026-06-01", "enabled": True},
}


# ---------- 预置法定节假日数据（2026 年国务院通知） ----------
LEGAL_HOLIDAY_PRESETS: Dict[int, List[Dict[str, Any]]] = {
    2026: [
        {"name": "元旦", "date": "2026-01-01"},
        {"name": "元旦", "date": "2026-01-02"},
        {"name": "春节调休上班", "date": "2026-02-14"},
        {"name": "春节", "date": "2026-02-16"},
        {"name": "春节", "date": "2026-02-17"},
        {"name": "春节", "date": "2026-02-18"},
        {"name": "春节", "date": "2026-02-19"},
        {"name": "春节", "date": "2026-02-20"},
        {"name": "春节", "date": "2026-02-21"},
        {"name": "春节", "date": "2026-02-22"},
        {"name": "春节调休上班", "date": "2026-02-28"},
        {"name": "清明节", "date": "2026-04-04"},
        {"name": "清明节", "date": "2026-04-05"},
        {"name": "清明节", "date": "2026-04-06"},
        {"name": "劳动节", "date": "2026-05-01"},
        {"name": "劳动节", "date": "2026-05-02"},
        {"name": "劳动节", "date": "2026-05-03"},
        {"name": "劳动节", "date": "2026-05-04"},
        {"name": "劳动节", "date": "2026-05-05"},
        {"name": "劳动节调休上班", "date": "2026-05-09"},
        {"name": "端午节", "date": "2026-06-19"},
        {"name": "端午节", "date": "2026-06-20"},
        {"name": "端午节", "date": "2026-06-21"},
        {"name": "中秋节", "date": "2026-09-25"},
        {"name": "中秋节", "date": "2026-09-26"},
        {"name": "中秋节", "date": "2026-09-27"},
        {"name": "国庆节", "date": "2026-10-01"},
        {"name": "国庆节", "date": "2026-10-02"},
        {"name": "国庆节", "date": "2026-10-03"},
        {"name": "国庆节", "date": "2026-10-04"},
        {"name": "国庆节", "date": "2026-10-05"},
        {"name": "国庆节", "date": "2026-10-06"},
        {"name": "国庆节", "date": "2026-10-07"},
        {"name": "国庆节", "date": "2026-10-08"},
        {"name": "国庆节调休上班", "date": "2026-10-10"},
        {"name": "国庆节调休上班", "date": "2026-10-11"},
    ],
}


# ---------- 二进制传感器配置（3 个独立 boolean 实体） ----------
BINARY_SENSOR_TYPES: Dict[str, Dict[str, Any]] = {
    ATTR_IS_WORKDAY: {
        "name": "工作日",
        "icon": "mdi:briefcase-check",
        "device_class": None,
        "info": True,  # 承载详细信息属性
    },
    ATTR_IS_HOLIDAY: {
        "name": "节假日",
        "icon": "mdi:calendar-star",
        "device_class": None,
    },
    ATTR_IS_STUDENT_HOLIDAY: {
        "name": "学生假期",
        "icon": "mdi:school",
        "device_class": None,
    },
}

# 星期名称
WEEKDAY_NAMES: Final[List[str]] = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
