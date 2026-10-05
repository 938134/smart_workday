"""Smart Workday integration."""

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
    KEY_HOLIDAYS,
    HOLIDAY_NAMES_ZH,
    empty_calendar_data,
)
from .coordinator import (
    SmartWorkdayDataManager, SmartWorkdayCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR]


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


async def _auto_import_legal_if_empty(hass: HomeAssistant, store: Store, entry: ConfigEntry):
    """启用法定假期开关时，按日期合并导入 chinese_calendar 提供的国务院法定假期。

    v2.20.0：数据源从硬编码 LEGAL_HOLIDAY_PRESETS 切换为 chinese-calendar 库。
    合并模式（保留 v2.19.1 修复）：
    - 逐条按 (单日|多日, 起, 止) 比对，已有条目保留用户数据，缺失条目补齐
    - 每次 reload 都会检查，用户清空某日能自动恢复；用户手工改动过的条目不会被覆盖
    - 目标年份取当前系统年（chinese-calendar 通常覆盖至当年）
    """
    try:
        data = await store.async_load()
        if not data:
            data = empty_calendar_data()
        holidays = data.setdefault(KEY_HOLIDAYS, [])

        import_year = date.today().year
        presets = _build_legal_holidays_from_calendar(import_year)
        if not presets:
            return

        # 已有条目去重键集合
        existing_keys = {
            _entry_dedup_key(item)
            for item in holidays
            if isinstance(item, dict)
        }

        # 补齐缺失条目（保留用户手工维护的条目）
        added = 0
        for item in presets:
            key = _entry_dedup_key(item)
            if key in existing_keys:
                continue
            entry_out = dict(item)
            entry_out["uid"] = str(uuid.uuid4())[:8]
            holidays.append(entry_out)
            existing_keys.add(key)
            added += 1

        if added:
            await store.async_save(data)
            _LOGGER.info(
                "已合并导入 %d 条 %d 年国务院法定假期（Store 已有 %d 条，共 %d 条预置）",
                added, import_year, len(holidays) - added, len(presets),
            )

    except Exception as e:
        _LOGGER.error("自动导入法定假期失败: %s", e)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """设置配置条目"""
    _LOGGER.debug("设置 %s: %s", DOMAIN_DISPLAY_NAME, entry.entry_id)

    # 创建 Store（JSON 持久化，存放在 .storage/ 目录）
    store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")

    # 自动导入法定假期：启用 legal 且当前无节假日数据时，自动从国务院通知预置数据导入
    if entry.data[CONF_ENABLED_LEGAL]:
        await _auto_import_legal_if_empty(hass, store, entry)

    # 初始化数据管理器
    data_manager = SmartWorkdayDataManager(hass, store)
    data_manager.update_enabled_flags(entry.data)

    # 初始化协调器
    coordinator = SmartWorkdayCoordinator(hass, entry.entry_id, data_manager)

    # 【临时诊断】定位"实体创建时不可用"—— HA 重启场景专用，定位后移除
    _LOGGER.warning(
        "[SW-DIAG] setup 开始: entry=%s hass_state=%s",
        entry.entry_id, hass.state,
    )

    await coordinator.async_config_entry_first_refresh()

    # 【临时诊断】首刷后的 coordinator 状态（available 的唯一来源）
    _LOGGER.warning(
        "[SW-DIAG] 首刷完成: last_update_success=%s data_keys=%s",
        coordinator.last_update_success,
        sorted(coordinator.data) if isinstance(coordinator.data, dict) else type(coordinator.data).__name__,
    )

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

    # 【临时诊断】平台加载完成（此时实体已创建并写过一次状态）
    _LOGGER.warning(
        "[SW-DIAG] 平台加载完成: entry=%s last_update_success=%s hass_state=%s",
        entry.entry_id, coordinator.last_update_success, hass.state,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置条目"""
    _LOGGER.debug("卸载 %s: %s", DOMAIN_DISPLAY_NAME, entry.entry_id)

    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True

    return False
