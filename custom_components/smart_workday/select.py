"""Select platform for Smart Workday - 假期类型下拉选择."""

import logging
from typing import Any, Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    HolidayType,
    HOLIDAY_TYPE_OPTIONS,
    HOLIDAY_TYPE_LABELS,
    DEFAULT_HOLIDAY_TYPE,
    ATTR_CURRENT_TYPE,
)

_LOGGER = logging.getLogger(__name__)


class HolidayTypeSelect(RestoreEntity, SelectEntity):
    """假期类型下拉实体 - 决定日历 UI 创建事件时归入哪个分类

    选项显示中文标签（带「放假/上班」语义），
    但 hass.data 里始终存英文机器值，日历分类逻辑不受影响。
    """

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry_id: str, device_info: DeviceInfo):
        self._hass = hass
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_holiday_type"
        self._attr_name = "假期类型"
        self._attr_icon = "mdi:format-list-bulleted-type"
        self._attr_device_info = device_info
        self._attr_should_poll = False
        # 选项用中文标签显示；调休补班不单独占选项（随法定假日一起设定）
        self._attr_options = [
            HOLIDAY_TYPE_LABELS[t] for t in HOLIDAY_TYPE_OPTIONS
        ]

    @staticmethod
    def _label_to_type(label: Optional[str]) -> Optional[HolidayType]:
        """中文标签 → HolidayType（兼容旧版本存的英文值）

        调休补班已合并进法定假日（随法定节假日一起设定），
        旧版单独选过的「调休补班（上班）」/ "makeup" 一律归入 LEGAL。
        """
        if not label:
            return None
        # 兼容上一版文案：旧标签「法定假日（放假）」与新标签「法定假日（放假/调休）」都归 LEGAL
        if label in ("法定假日（放假）",):
            return HolidayType.LEGAL
        if label in ("调休补班（上班）", "调休补班", HolidayType.MAKEUP.value):
            return HolidayType.LEGAL
        for htype, lbl in HOLIDAY_TYPE_LABELS.items():
            if label == lbl:
                return htype
        # 向后兼容：旧版本选项是英文 value
        try:
            return HolidayType(label)
        except (ValueError, TypeError):
            return None

    @classmethod
    def _type_to_label(cls, htype: HolidayType) -> str:
        """HolidayType → 中文标签"""
        return HOLIDAY_TYPE_LABELS[htype]

    async def async_added_to_hass(self) -> None:
        """实体加入 HA 时，恢复上次状态"""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        htype = (
            self._label_to_type(last_state.state)
            if last_state is not None
            else None
        )
        if htype is None:
            htype = DEFAULT_HOLIDAY_TYPE
            _LOGGER.debug("无历史状态，使用默认假期类型: %s", htype.display_name)
        else:
            _LOGGER.debug("恢复假期类型: %s", htype.display_name)

        self._attr_current_option = self._type_to_label(htype)
        self._update_data_holder(htype.value)

    def _update_data_holder(self, value: str) -> None:
        """更新 hass.data 里的当前类型（存英文机器值），供日历 UI 读取"""
        data = self._hass.data.get(DOMAIN, {}).get(self._entry_id)
        if data is not None:
            data[ATTR_CURRENT_TYPE] = value

    async def async_select_option(self, option: str) -> None:
        """用户切换下拉选项"""
        htype = self._label_to_type(option)
        if htype is None:
            _LOGGER.warning("无效的假期类型: %s", option)
            return

        self._attr_current_option = self._type_to_label(htype)
        self._update_data_holder(htype.value)
        self.async_write_ha_state()

        _LOGGER.info(
            "假期类型切换为: %s (%s)", htype.display_name, htype.data_category
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """返回当前类型的中文说明、英文机器值和显示标签"""
        htype = self._label_to_type(self._attr_current_option)
        if htype is None:
            return {}
        return {
            "value": htype.value,  # 英文机器值，供自动化判断使用
            "display_name": htype.display_name,
            "display_label": HOLIDAY_TYPE_LABELS[htype],
            "data_category": htype.data_category,
            "is_makeup": htype.is_makeup,
            "effect": "上班" if htype.is_makeup else "放假",
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置 select 实体"""
    _LOGGER.debug("设置假期类型 select: %s", entry.entry_id)

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get("name", "智能工作日"),
        manufacturer="Smart Workday",
        model="工作日传感器",
        sw_version="2.2.0",
    )

    async_add_entities([HolidayTypeSelect(hass, entry.entry_id, device_info)])
    _LOGGER.info("已添加假期类型 select 实体")
