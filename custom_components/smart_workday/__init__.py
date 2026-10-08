"""Smart Workday integration.

v3.1.0：实体按 2 个设备分区，配置 UI 也按 2 段（传感器 / 诊断）
- 传感器设备：假期日历 + 工作日
- 诊断设备：法定假期 + 自定义假期
- 日历实体增加详细状态属性（进行中/空闲、当前事件、未来事件、数据统计）

v3.0.0 破坏性重构：
- 引入 migrate_v1_to_v2：老 Store 结构（holidays/studentdays/customdays）无损迁移到新结构（legal/custom）
  - holidays → legal（原样）
  - studentdays → custom，每条加 category="学生"
  - customdays  → custom，每条加 category="自定义"
- 顶层开关 3 → 2：entry.data 中 enabled_student 被忽略（迁移时保留但不再使用）
"""

import logging
import uuid
from datetime import date
from typing import Dict, List, Tuple

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    DOMAIN_DISPLAY_NAME,
    STORAGE_VERSION,
    CONF_ENABLED_LEGAL,
    KEY_LEGAL,
    KEY_CUSTOM,
    LEGACY_KEY_HOLIDAYS,
    LEGACY_KEY_STUDENTDAYS,
    LEGACY_KEY_CUSTOMDAYS,
    LEGACY_KEYS_DETECTION,
    HOLIDAY_NAMES_ZH,
    empty_calendar_data,
)
from .coordinator import (
    SmartWorkdayDataManager, SmartWorkdayCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR]


# ============================================================
# 从 chinese_calendar 库生成法定假期条目
# ============================================================
def _build_legal_holidays_from_calendar(year: int) -> List[Dict[str, str]]:
    """从 chinese_calendar 库生成某年法定假期条目列表。

    v2.20.0：改用 chinese-calendar 库替代硬编码 LEGAL_HOLIDAY_PRESETS。

    输出格式：
    - 多日假期合并为一条 range 条目：{"name", "start", "end"}
    - 单日假期用 date 字段：{"name", "date"}
    - 补班日（调休上班）单独生成单日条目，name 里带"调休上班"以便
      MAKEUP_KEYWORD 识别为 special workday

    chinese-calendar 覆盖 2004~2026 年，超出范围返回空列表。
    需要 chinese-calendar>=1.11.0，见 manifest.json requirements。
    """
    try:
        from chinese_calendar import holidays as _holidays, workdays as _workdays
    except ImportError:
        _LOGGER.warning("chinese-calendar 未安装，无法自动导入法定假期")
        return []

    # 法定节假日：按假期名分组，连续日期合并为 range 条目
    groups: Dict[str, List[date]] = {}
    for d, name_en in sorted(_holidays.items()):
        if d.year == year:
            name_zh = HOLIDAY_NAMES_ZH.get(name_en, name_en)
            groups.setdefault(name_zh, []).append(d)

    entries: List[Dict[str, str]] = []
    for name_zh, dates in groups.items():
        start, end = dates[0], dates[-1]
        if start == end:
            entries.append({"name": name_zh, "date": start.isoformat()})
        else:
            entries.append({
                "name": name_zh,
                "start": start.isoformat(),
                "end": end.isoformat(),
            })

    # 补班日：一般单日，name 里带"调休上班"关键词
    makeup_groups: Dict[str, List[date]] = {}
    for d, name_en in sorted(_workdays.items()):
        if d.year == year:
            base_zh = HOLIDAY_NAMES_ZH.get(name_en, name_en)
            makeup_groups.setdefault(f"{base_zh}调休上班", []).append(d)

    for name_zh, dates in makeup_groups.items():
        for d in dates:
            entries.append({"name": name_zh, "date": d.isoformat()})

    # 按开始日期排序
    entries.sort(key=lambda x: x.get("date") or x.get("start", ""))
    return entries


def _entry_dedup_key(item: Dict) -> Tuple:
    """生成条目的去重键：range 条目按 (start, end)，单日条目按 (date,)。"""
    if "date" in item:
        return ("single", item["date"])
    return ("range", item.get("start", ""), item.get("end", ""))


# ============================================================
# v1 → v2 Store 结构迁移
# ============================================================
def migrate_v1_to_v2(data: Dict) -> Dict:
    """把 v1 Store 结构（holidays/studentdays/customdays）无损迁移为 v2（legal/custom）。

    迁移规则：
    - holidays → legal（原样保留，含 uid、name、date/start/end）
    - studentdays → custom，每条追加 category="学生"
    - customdays → custom，每条追加 category="自定义"
    - 已迁移到 v2 结构的 data 原样返回（幂等）

    幂等性：只要 data 已含 KEY_LEGAL 或 KEY_CUSTOM，就视为已迁移，直接返回原对象。
    """
    if not data:
        return empty_calendar_data()

    # 已迁移
    if KEY_LEGAL in data or KEY_CUSTOM in data:
        return data

    # 无任何 legacy 字段 → 空数据
    if not any(k in data for k in LEGACY_KEYS_DETECTION):
        return empty_calendar_data()

    migrated: Dict[str, List[Dict]] = {"legal": [], "custom": []}

    # holidays → legal
    for item in data.get(LEGACY_KEY_HOLIDAYS, []) or []:
        if isinstance(item, dict):
            migrated["legal"].append(dict(item))

    # studentdays → custom（category="学生"）
    for item in data.get(LEGACY_KEY_STUDENTDAYS, []) or []:
        if not isinstance(item, dict):
            continue
        new_item = dict(item)
        new_item.setdefault("category", "学生")
        migrated["custom"].append(new_item)

    # customdays → custom（category="自定义"）
    for item in data.get(LEGACY_KEY_CUSTOMDAYS, []) or []:
        if not isinstance(item, dict):
            continue
        new_item = dict(item)
        new_item.setdefault("category", "自定义")
        migrated["custom"].append(new_item)

    # 按日期排序（保持与 _async_save_sync 一致的排序）
    for key in ("legal", "custom"):
        migrated[key].sort(key=lambda x: x.get("date") or x.get("start", ""))

    return migrated


async def _async_migrate_if_needed(hass: HomeAssistant, store: Store) -> None:
    """检测 Store 是否为 v1 结构，是则迁移并保存。"""
    try:
        data = await store.async_load()
        if not data:
            return  # 空 Store，无需迁移

        if KEY_LEGAL in data or KEY_CUSTOM in data:
            return  # 已是 v2，跳过

        if not any(k in data for k in LEGACY_KEYS_DETECTION):
            return  # 无 legacy 字段，跳过

        new_data = migrate_v1_to_v2(data)
        await store.async_save(new_data)
        _LOGGER.info(
            "Store 已从 v1 迁移到 v2（legal=%d, custom=%d）",
            len(new_data.get(KEY_LEGAL, [])),
            len(new_data.get(KEY_CUSTOM, [])),
        )
    except Exception as e:
        _LOGGER.error("Store 迁移失败: %s", e)


# ============================================================
# 法定假期自动导入
# ============================================================
async def _auto_import_legal_if_empty(hass: HomeAssistant, store: Store, entry: ConfigEntry):
    """启用法定假期开关时，按日期合并导入 chinese_calendar 提供的国务院法定假期。

    合并模式：逐条按 (单日|多日, 起, 止) 比对，已有条目保留用户数据，缺失条目补齐。
    用户手工改动过的条目不会被覆盖；用户清空某日能自动恢复。
    """
    try:
        data = await store.async_load()
        if not data:
            data = empty_calendar_data()
        legal = data.setdefault(KEY_LEGAL, [])

        import_year = date.today().year
        presets = _build_legal_holidays_from_calendar(import_year)
        if not presets:
            return

        # 已有条目去重键集合
        existing_keys = {
            _entry_dedup_key(item)
            for item in legal
            if isinstance(item, dict)
        }

        added = 0
        for item in presets:
            key = _entry_dedup_key(item)
            if key in existing_keys:
                continue
            entry_out = dict(item)
            entry_out["uid"] = str(uuid.uuid4())[:8]
            legal.append(entry_out)
            existing_keys.add(key)
            added += 1

        if added:
            await store.async_save(data)
            _LOGGER.info(
                "已合并导入 %d 条 %d 年国务院法定假期（Store 已有 %d 条，共 %d 条预置）",
                added, import_year, len(legal) - added, len(presets),
            )

    except Exception as e:
        _LOGGER.error("自动导入法定假期失败: %s", e)


# ============================================================
# setup / unload
# ============================================================
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """设置配置条目"""
    _LOGGER.debug("设置 %s: %s", DOMAIN_DISPLAY_NAME, entry.entry_id)

    # 创建 Store（JSON 持久化，存放在 .storage/ 目录）
    store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")

    # 老 Store（v1）→ v2 迁移（幂等）
    await _async_migrate_if_needed(hass, store)

    # 自动导入法定假期：启用 legal 且当前无节假日数据时，自动从 chinese-calendar 导入
    if entry.data.get(CONF_ENABLED_LEGAL, True):
        await _auto_import_legal_if_empty(hass, store, entry)

    # 初始化数据管理器
    data_manager = SmartWorkdayDataManager(hass, store)
    data_manager.update_enabled_flags(entry.data)

    # 初始化协调器
    coordinator = SmartWorkdayCoordinator(hass, entry.entry_id, data_manager)

    await coordinator.async_config_entry_first_refresh()

    # 存储数据
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "config": entry.data,
        "coordinator": coordinator,
        "data_manager": data_manager,
        "store": store,
    }

    # 设置平台
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置条目"""
    _LOGGER.debug("卸载 %s: %s", DOMAIN_DISPLAY_NAME, entry.entry_id)

    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True

    return False
