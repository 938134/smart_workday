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

# 当前假期类型（存 hass.data，供日历 UI 创建事件时读取）
ATTR_CURRENT_TYPE: Final = "current_holiday_type"


# ---------- 假期分类（日历 UI 选择用） ----------
class HolidayType(str, Enum):
    """假期类型 - 用于日历 UI 创建事件时下拉选择

    用户在 Lovelace 的 select 实体里选好类型，
    然后去日历面板点击添加，自动归入对应分类。

    下拉只暴露 3 类（自定义/法定/学生）；
    MAKEUP（调休上班日）是内部类型，不单独占用选项——
    选「法定假日」时名称/描述含「调休」即自动归为调休上班日，
    与国务院通知的「放假几天+调休几天」一套设定一致。
    """
    CUSTOM = "custom"      # 自定义假期 → customdays
    STUDENT = "student"    # 学生假期 → studentdays
    LEGAL = "legal"        # 法定节假日（含调休）→ holidays
    MAKEUP = "makeup"      # 调休上班日（内部类型）→ holidays（名称自动加「调休」后缀）

    @property
    def display_name(self) -> str:
        return _TYPE_NAMES[self]

    @property
    def icon(self) -> str:
        return _TYPE_ICONS[self]

    @property
    def data_category(self) -> str:
        """映射到数据的分类键"""
        return _TYPE_TO_CATEGORY[self]

    @property
    def is_makeup(self) -> bool:
        """是否调休上班日"""
        return self == HolidayType.MAKEUP


_TYPE_NAMES: Dict[HolidayType, str] = {
    HolidayType.CUSTOM: "自定义假日",
    HolidayType.STUDENT: "学生假期",
    HolidayType.LEGAL: "法定假日",
    HolidayType.MAKEUP: "调休补班",
}

_TYPE_ICONS: Dict[HolidayType, str] = {
    HolidayType.CUSTOM: "mdi:star-circle",
    HolidayType.STUDENT: "mdi:school",
    HolidayType.LEGAL: "mdi:calendar-star",
    HolidayType.MAKEUP: "mdi:briefcase-clock",
}

# 类型 → yaml 分类映射
_TYPE_TO_CATEGORY: Dict[HolidayType, str] = {
    HolidayType.CUSTOM: "customdays",
    HolidayType.STUDENT: "studentdays",
    HolidayType.LEGAL: "holidays",
    HolidayType.MAKEUP: "holidays",
}

# select 实体选项顺序（自定义最常用，放第一）
# 调休上班日不单独占选项：选「法定假日」时名称/描述含「调休」自动归为调休上班日
HOLIDAY_TYPE_OPTIONS: Final[List[HolidayType]] = [
    HolidayType.CUSTOM,
    HolidayType.LEGAL,
    HolidayType.STUDENT,
]

# select 选项的显示标签（带放假/上班语义，避免混淆）
# 法定假日标签标注「含调休」，调休上班日随法定节假日一起设定
HOLIDAY_TYPE_LABELS: Final[Dict[HolidayType, str]] = {
    HolidayType.CUSTOM: "自定义假日（放假）",
    HolidayType.LEGAL: "法定假日（放假/调休）",
    HolidayType.STUDENT: "学生假期（放假）",
    HolidayType.MAKEUP: "调休补班（上班）",
}

# 默认类型
DEFAULT_HOLIDAY_TYPE: Final[HolidayType] = HolidayType.CUSTOM


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