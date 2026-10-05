"""Constants for Smart Workday.

版本号统一在此维护：所有 Python 模块通过 `from .const import VERSION` 引用。
manifest.json 需手动同步（HA 无法从 const.py 动态读取）。
"""

from typing import Any, Final, Dict, List

# ============================================================
# 版本号（唯一权威来源，其它 Python 模块必须从此引用）
# ============================================================
VERSION: Final = "2.20.0"

# 存储版本号（Store JSON 持久化）
STORAGE_VERSION: Final = 1

# Store 数据结构的三个字段名（唯一权威来源）
KEY_HOLIDAYS: Final = "holidays"
KEY_STUDENTDAYS: Final = "studentdays"
KEY_CUSTOMDAYS: Final = "customdays"
CALENDAR_KEYS: Final = (KEY_HOLIDAYS, KEY_STUDENTDAYS, KEY_CUSTOMDAYS)

# 空日历数据工厂（每次调用返回新字典，避免共享可变对象）
def empty_calendar_data() -> Dict[str, List[Dict[str, Any]]]:
    return {
        KEY_HOLIDAYS: [],
        KEY_STUDENTDAYS: [],
        KEY_CUSTOMDAYS: [],
    }


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

# 日历 UI 手动添加事件时，根据名称关键词推断分类（用于区分调休）
MAKEUP_KEYWORD: Final = "调休"


# ============================================================
# chinese_calendar 库英文假期名 → 中文显示名映射
# v2.20.0 起改用 chinese-calendar 库替代硬编码 LEGAL_HOLIDAY_PRESETS，
# 本映射保证 UI 上仍是中文假期名（如 "国庆节" 而非 "National Day"）。
# ============================================================
HOLIDAY_NAMES_ZH: Final[Dict[str, str]] = {
    "New Year's Day": "元旦",
    "Spring Festival": "春节",
    "Tomb-sweeping Day": "清明节",
    "Labour Day": "劳动节",
    "Dragon Boat Festival": "端午节",
    "National Day": "国庆节",
    "Mid-autumn Festival": "中秋节",
    "Anti-Fascist 70th Day": "抗战胜利纪念日",
}


# ============================================================
# 星期名称
# ============================================================
WEEKDAY_NAMES: Final[List[str]] = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
