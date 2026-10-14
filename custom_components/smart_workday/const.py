"""Constants for Smart Workday.

版本号与集成名称：均从 manifest.json 读取（manifest.json 是唯一权威来源）。
CI 会校验 README badge ↔ manifest.json 一致性（见 .github/workflows/release.yml）。

v3.1.2：版本号统一管理（manifest.json 唯一权威）+ Release 自动带更新内容
- manifest.json 是版本号 / 应用名称 / domain 的唯一权威来源
- hacs.json 精简（HACS 从 manifest 自动 fallback）
- release.yml 全部从 manifest 派生元数据，README changelog 自动注入 Release 描述

v3.1.1：图标焕新（512x512 HACS 规范「2月30日」彩蛋）+ 修复 v3.1.0 遗漏导入 + 合并诊断设备
- 单设备「智能工作日」，实体按 EntityCategory 分传感器/诊断 2 分区
- 修复 BINARY_SENSOR_IS_WORKDAY 等常量误删导致的 ImportError

v3.1.0：实体按 EntityCategory 分区，配置 UI 也按 2 段（传感器 / 诊断）
- 传感器区：工作日 + 假期日历（2 个开关）
- 诊断区：法定假期 + 自定义假期（2 个开关，EntityCategory.DIAGNOSTIC）

v3.0.0 破坏性重构：
- Store 结构从 3 分类（holidays/studentdays/customdays）合并为 2 分类（legal/custom）
  学生假期实质是自定义假期的一个类别，每条 custom 条目带 category 字段
- 顶层开关 3 → 2：删除 enabled_student
- Binary sensor 4 → 3：删除 is_student_holiday，信息通过 active_custom 属性暴露
- DayInfo 去掉 is_student_holiday，新增 active_custom: Dict[str, List[str]]
"""

import json
import logging
from pathlib import Path
from typing import Any, Final, Dict, List

_LOGGER = logging.getLogger(__name__)

# ============================================================
# manifest.json 读取（VERSION 与集成名称的唯一权威数据源）
# ============================================================
_MANIFEST_PATH = Path(__file__).parent / "manifest.json"
try:
    with open(_MANIFEST_PATH, encoding="utf-8") as f:
        _MANIFEST = json.load(f)
    VERSION: Final = _MANIFEST.get("version", "0.0.0")
    DEFAULT_NAME: Final = _MANIFEST.get("name", "Smart Workday")
except (OSError, json.JSONDecodeError) as e:
    _LOGGER.error("读取 manifest.json 失败: %s，使用默认值", e)
    VERSION = "0.0.0"
    DEFAULT_NAME = "Smart Workday"

# 存储版本号（Store JSON 持久化，v3.0.0 起为 2）
STORAGE_VERSION: Final = 2

# Store 数据结构的两个字段名（唯一权威来源）
KEY_LEGAL: Final = "legal"
KEY_CUSTOM: Final = "custom"
CALENDAR_KEYS: Final = (KEY_LEGAL, KEY_CUSTOM)

# 旧版 Store 结构字段（仅迁移函数使用，不要在生产代码引用）
LEGACY_KEY_HOLIDAYS: Final = "holidays"
LEGACY_KEY_STUDENTDAYS: Final = "studentdays"
LEGACY_KEY_CUSTOMDAYS: Final = "customdays"

# 空日历数据工厂（每次调用返回新字典，避免共享可变对象）
def empty_calendar_data() -> Dict[str, List[Dict[str, Any]]]:
    return {
        KEY_LEGAL: [],
        KEY_CUSTOM: [],
    }

# 老 Store 结构检测：只要出现以下任一字段就判定为 v1，触发迁移
LEGACY_KEYS_DETECTION: Final = (LEGACY_KEY_HOLIDAYS, LEGACY_KEY_STUDENTDAYS, LEGACY_KEY_CUSTOMDAYS)


# ============================================================
# 集成标识（DEFAULT_NAME 与 VERSION 已从 manifest.json 读取）
# ============================================================
DOMAIN: Final = "smart_workday"
DOMAIN_DISPLAY_NAME: Final = "Smart Workday"  # 设备 manufacturer（英文）

# 实体与设备元数据
BINARY_SENSOR_MODEL: Final = "工作日传感器"

# 单日历实体名称（显示所有分类，description 标注来源）
CALENDAR_ENTITY_NAME: Final = "假期日历"
CALENDAR_UNIQUE_SUFFIX: Final = "_calendar"


# ============================================================
# 顶层数据开关（v3.0.0 起）：控制 Store 里是否导入/保留对应数据
# v3.1.0：与实体可见性解耦，仅控制数据来源，不影响 UI 显示
# ============================================================
CONF_ENABLED_LEGAL: Final = "enabled_legal"      # 是否导入/保留法定假期数据
CONF_ENABLED_CUSTOM: Final = "enabled_custom"    # 是否保留自定义假期数据
CONF_NAME: Final = "name"

# ============================================================
# 传感器实体可见性开关（v3.1.0 新增）：每个实体独立开关
# ============================================================
CONF_ENABLED_LEGAL_SENSOR: Final = "enabled_legal_holiday_sensor"
CONF_ENABLED_WORKDAY_SENSOR: Final = "enabled_workday_sensor"
CONF_ENABLED_CALENDAR: Final = "enabled_calendar"
CONF_ENABLED_CUSTOM_SENSOR: Final = "enabled_custom_holiday_sensor"

# OptionsFlow 表单字段
CONF_START_DATE: Final = "start_date"
CONF_END_DATE: Final = "end_date"
CONF_CUSTOM_NAME: Final = "custom_name"
CONF_CATEGORY: Final = "category"  # 添加假期时选择的类别


# ============================================================
# 默认推荐类别（UI 下拉快捷选项，也支持用户自定义输入）
# ============================================================
DEFAULT_CUSTOM_CATEGORIES: Final[List[str]] = ["学生", "工作", "个人", "家庭"]


# ============================================================
# Binary Sensor 实体配置（v3.0.0 起 3 个）
# ============================================================
BINARY_SENSOR_IS_WORKDAY: Final = "工作日"
BINARY_SENSOR_IS_HOLIDAY: Final = "法定假期"
BINARY_SENSOR_IS_CUSTOM_HOLIDAY: Final = "自定义假期"

# 属性键名（供 binary_sensor.attributes 读取，保留富信息）
ATTR_IS_WORKDAY: Final = "is_workday"
ATTR_IS_HOLIDAY: Final = "is_holiday"
ATTR_IS_WEEKEND: Final = "is_weekend"
ATTR_IS_SPECIAL_WORKDAY: Final = "is_special_workday"
ATTR_IS_CUSTOM_HOLIDAY: Final = "is_custom_holiday"
ATTR_ACTIVE_CUSTOM: Final = "active_custom"  # {"学生": ["寒假"], "工作": ["出差"]}
ATTR_DAY_TYPE: Final = "day_type"


# ============================================================
# 日历事件来源标签（description 前缀，用于单日历 UI 区分来源）
# ============================================================
EVENT_SOURCE_LEGAL: Final = "📅 法定假期"
EVENT_SOURCE_CUSTOM: Final = "🎉 自定义假期"  # 后面追加类别：🎉 自定义假期 · 学生
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
