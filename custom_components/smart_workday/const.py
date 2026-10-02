"""Constants for Smart Workday."""

from enum import Enum
from typing import Final, Dict, List

DOMAIN: Final = "smart_workday"
DEFAULT_NAME: Final = "智能工作日"


class HolidayMode(str, Enum):
    """假期模式"""
    STANDARD = "standard"  # 标准模式：法定+自定义
    CUSTOM = "custom"      # 自由模式：仅自定义

    @property
    def display_name(self) -> str:
        """获取显示名称"""
        return _MODE_NAMES[self]

    @property
    def description(self) -> str:
        """获取模式描述"""
        return _MODE_DESCRIPTIONS[self]

    @property
    def icon(self) -> str:
        """获取模式图标"""
        return _MODE_ICONS[self]


# 模式名称映射
_MODE_NAMES: Dict[HolidayMode, str] = {
    HolidayMode.STANDARD: "标准模式",
    HolidayMode.CUSTOM: "自由模式",
}

# 模式描述映射
_MODE_DESCRIPTIONS: Dict[HolidayMode, str] = {
    HolidayMode.STANDARD: "法定节假日 + 自定义假期",
    HolidayMode.CUSTOM: "只有自定义假期算放假",
}

# 模式图标映射
_MODE_ICONS: Dict[HolidayMode, str] = {
    HolidayMode.STANDARD: "📅",
    HolidayMode.CUSTOM: "🌟",
}


# ---------- 属性常量（供二进制传感器属性读取） ----------
ATTR_IS_WORKDAY: Final = "is_workday"
ATTR_IS_HOLIDAY: Final = "is_holiday"
ATTR_IS_WEEKEND: Final = "is_weekend"
ATTR_IS_SPECIAL_WORKDAY: Final = "is_special_workday"
ATTR_IS_STUDENT_HOLIDAY: Final = "is_student_holiday"

# ---------- 日历类型（3 个独立日历实体） ----------
class CalendarType(str, Enum):
    """日历类型 - 每个类型一个独立日历实体，事件自动归类"""
    LEGAL = "legal"        # 法定节假日（含调休）→ holidays
    STUDENT = "student"    # 学生假期 → studentdays
    CUSTOM = "custom"      # 自定义假期 → customdays

    @property
    def display_name(self) -> str:
        return _CAL_NAMES[self]

    @property
    def data_category(self) -> str:
        """映射到数据的分类键"""
        return _CAL_TO_CATEGORY[self]


_CAL_NAMES: Dict[CalendarType, str] = {
    CalendarType.LEGAL: "法定节假日",
    CalendarType.STUDENT: "学生假期",
    CalendarType.CUSTOM: "自定义假期",
}

_CAL_TO_CATEGORY: Dict[CalendarType, str] = {
    CalendarType.LEGAL: "holidays",
    CalendarType.STUDENT: "studentdays",
    CalendarType.CUSTOM: "customdays",
}


# 二进制传感器配置 - 3 个独立 boolean 实体
# 用户直接读取：is_workday（是否工作日）/ is_holiday（是否节假日）/ is_student_holiday（是否学生假期）
# 详细信息（是否双休、是否调休、事件列表、日期、模式等）作为属性挂在 is_workday 上
BINARY_SENSOR_TYPES: Dict[str, Dict[str, str]] = {
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