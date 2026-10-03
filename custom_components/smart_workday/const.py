"""Constants for Smart Workday.

版本号统一在此维护：所有 Python 模块通过 `from .const import VERSION` 引用。
manifest.json 需手动同步（HA 无法从 const.py 动态读取）。
"""

from datetime import datetime
from typing import Any, Final, Dict, List

# ============================================================
# 版本号（唯一权威来源，其它 Python 模块必须从此引用）
# ============================================================
VERSION: Final = "2.15.1"

# 存储版本号（Store JSON 持久化）
STORAGE_VERSION: Final = 1


# ============================================================
# 集成标识与默认名称（唯一权威来源，避免各处硬编码）
# ============================================================
DOMAIN: Final = "smart_workday"
DEFAULT_NAME: Final = "智能工作日"          # 集成显示名称默认值
DOMAIN_DISPLAY_NAME: Final = "Smart Workday"  # 设备 manufacturer（英文）

# 实体与设备元数据
BINARY_SENSOR_MODEL: Final = "工作日传感器"

# 单日历实体名称（显示所有分类，description 标注来源）
CALENDAR_ENTITY_NAME: Final = "假期日历"
CALENDAR_UNIQUE_SUFFIX: Final = "_calendar"


# ============================================================
# 顶层启用开关（entry.data 键名）
# ============================================================
CONF_ENABLED_LEGAL: Final = "enabled_legal"
CONF_ENABLED_STUDENT: Final = "enabled_student"
CONF_ENABLED_CUSTOM: Final = "enabled_custom"
CONF_NAME: Final = "name"

# OptionsFlow 表单字段
CONF_START_DATE: Final = "start_date"
CONF_END_DATE: Final = "end_date"
CONF_CUSTOM_NAME: Final = "custom_name"


# ============================================================
# Binary Sensor 实体配置（4 个布尔传感器）
# ============================================================
# 实体名称（binary_sensor 平台，状态 on/off）
BINARY_SENSOR_IS_WORKDAY: Final = "工作日"
BINARY_SENSOR_IS_HOLIDAY: Final = "法定假期"
BINARY_SENSOR_IS_STUDENT_HOLIDAY: Final = "学生假期"
BINARY_SENSOR_IS_CUSTOM_HOLIDAY: Final = "自定义假期"

# 属性键名（供 binary_sensor.attributes 读取，保留富信息）
ATTR_IS_WORKDAY: Final = "is_workday"
ATTR_IS_HOLIDAY: Final = "is_holiday"
ATTR_IS_WEEKEND: Final = "is_weekend"
ATTR_IS_SPECIAL_WORKDAY: Final = "is_special_workday"
ATTR_IS_STUDENT_HOLIDAY: Final = "is_student_holiday"
ATTR_IS_CUSTOM_HOLIDAY: Final = "is_custom_holiday"
ATTR_DAY_TYPE: Final = "day_type"


# ============================================================
# 日历事件类型标记（description 前缀，用于单日历 UI 区分来源）
# ============================================================
EVENT_SOURCE_LEGAL: Final = "📅 法定假期"
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

# 日历 UI 手动添加事件时，根据名称关键词推断分类（仅法定日历需要，用于区分调休）
STUDENT_HOLIDAY_KEYWORDS: Final = ("寒假", "暑假", "春假", "秋假", "儿童节", "学生")
MAKEUP_KEYWORD: Final = "调休"


# ============================================================
# 预置法定假期数据（国务院通知，按需扩展年份）
# ============================================================
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


def _default_legal_year() -> int:
    """根据当前年份自动计算默认导入年份。

    优先级：
    1. 当前年份（若预置数据包含该年）
    2. 最近可用年份（<= 当前年的最大值）
    3. 最早的可用年份（所有预置年份都在未来时）
    4. 当前年份（无预置数据时兜底）
    """
    current = datetime.now().year
    years = sorted(LEGAL_HOLIDAY_PRESETS.keys())
    if not years:
        return current
    if current in years:
        return current
    for y in reversed(years):
        if y <= current:
            return y
    return years[0]


# 一键导入的默认年份（根据当前年份自动计算，无需硬编码）
DEFAULT_LEGAL_YEAR: Final = _default_legal_year()


# ============================================================
# 星期名称
# ============================================================
WEEKDAY_NAMES: Final[List[str]] = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
