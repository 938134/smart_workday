# Smart Workday 智能工作日

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Version](https://img.shields.io/badge/version-2.3.0-blue)]()

Home Assistant 自定义集成，智能判断当天是否为工作日，支持法定节假日、学生假期和自定义假期。

## 功能特点

- **3 个独立日历** — 法定/学生/自定义各有专属日历，点击即归类，无需切换
- **调休自动识别** — 法定假日名称含「调休」自动归为上班日
- **3 个 boolean 实体** — `is_workday` / `is_holiday` / `is_student_holiday`，自动化直接用 ON/OFF
- **详细信息放属性** — 日期、星期、模式、是否调休、事件列表等挂在 `is_workday` 实体属性中
- **Store 持久化** — 数据存储在 HA 标准 `.storage/` 目录，升级不丢失
- **双语支持** — 中文/英文界面
- **零外部依赖** — 纯本地运行，仅需 pyyaml（用于数据迁移）

## 安装

### HACS（推荐）

1. HACS → 集成 → 右上角菜单 → 自定义仓库
2. 添加仓库：`https://github.com/938134/smart-workday`
3. 搜索 "Smart Workday" 并安装

### 手动安装

将 `custom_components/smart_workday` 文件夹复制到 HA 的 `custom_components` 目录，重启 HA。

## 快速开始

### 第一步：添加集成

设置 → 设备与服务 → 添加集成 → 搜索 "Smart Workday"

### 第二步：选择假期模式

| 模式 | 说明 |
|---|---|
| 📅 **标准模式** | 法定节假日 + 自定义假期 |
| 🌟 **自由模式** | 只有自定义假期算放假（法定节假日当工作日） |

### 第三步：添加假期

打开日历面板，选择对应日历 → 点击日期 → 填写名称 → 保存。

| 日历 | 用途 |
|---|---|
| **法定节假日日历** | 元旦、春节、国庆等国务院节假日，名称含「调休」自动识别为上班日 |
| **学生假期日历** | 寒假、暑假、春假、秋假、儿童节等 |
| **自定义假期日历** | 结婚纪念日、生日、自定义纪念日等 |

> 💡 **调休怎么用？** 在「法定节假日日历」中添加，名称写「XX调休」即可，系统自动识别为上班日。

## 生成的实体

集成生成 5 个实体：3 个 boolean 二进制传感器 + 3 个日历（法定节假日/学生假期/自定义假期）。

### 1. 工作日（核心 boolean）

- **实体**: `binary_sensor.智能工作日_工作日`
- **状态**: ON = 今天是工作日（含调休上班），OFF = 非工作日
- **属性**: 承载所有详细信息（自动化首选实体）
  - `is_workday` / `is_holiday` / `is_weekend` / `is_special_workday` / `is_student_holiday` — 布尔标志
  - `date` / `weekday` — 日期与星期
  - `mode` — 当前假期模式
  - `holiday_name` / `events` — 今日主事件名与事件列表
  - `upcoming` — 未来 7 天有事件的日期

### 2. 节假日

- **实体**: `binary_sensor.智能工作日_节假日`
- **状态**: ON = 今天是节假日（含法定/自定义），OFF = 不是
- **特性**: 纯粹 boolean，无属性

### 3. 学生假期

- **实体**: `binary_sensor.智能工作日_学生假期`
- **状态**: ON = 今天是学生假期，OFF = 不是
- **特性**: 纯粹 boolean，无属性
- **注意**: 学生假期不影响工作日判断，独立传感器

### 4-6. 三个日历

- **法定节假日日历** — 显示所有法定节假日事件，支持面板直接增删
- **学生假期日历** — 显示所有学生假期事件，支持面板直接增删
- **自定义假期日历** — 显示所有自定义假期事件，支持面板直接增删

## 数据格式

数据存储在 HA 的 `.storage/smart_workday.<entry_id>` 文件（JSON 格式）：

```json
{
  "holidays": [
    {"name": "元旦", "date": "2026-01-01", "uid": "abc12345"},
    {"name": "春节", "start": "2026-02-17", "end": "2026-02-23", "uid": "def67890"},
    {"name": "元旦调休", "date": "2026-01-04", "uid": "ghi11111"}
  ],
  "customdays": [
    {"name": "植树节", "date": "2026-03-12", "uid": "jkl22222"}
  ],
  "studentdays": [
    {"name": "暑假", "start": "2026-07-10", "end": "2026-08-31", "uid": "mno33333"}
  ]
}
```

> ⚠️ **注意**：学生假期（`studentdays`）不影响工作日判断，只触发独立的学生假期传感器。

### 从旧版 YAML 迁移

如果你从 v2.0.0 升级，集成会自动检测旧版 `calendar.yaml` 文件并迁移数据到 Store。无需手动操作。

## 配置管理

### 日常增删假期

直接用 HA 日历面板：

- **添加**: 选择对应日历 → 点击日期 → 填名称 → 保存
- **删除**: 选择对应日历 → 点击事件 → 删除

### 修改假期模式

设置 → 设备与服务 → Smart Workday → 配置 → 切换模式 → 保存

### 高级编辑

配置 → 选择「高级：直接编辑数据」→ 编辑 JSON → 保存

## 自动化示例

```yaml
# 工作日开灯
trigger:
  - platform: time
    at: "07:00:00"
condition:
  - condition: state
    entity_id: binary_sensor.智能工作日_工作日
    state: "on"
action:
  - service: light.turn_on
    target:
      entity_id: light.bedroom
```

```yaml
# 节假日推送通知
trigger:
  - platform: state
    entity_id: binary_sensor.智能工作日_节假日
    to: "on"
action:
  - service: notify.mobile_app
    data:
      message: "🎊 今天是节假日！{{ states.binary_sensor.智能工作日_工作日.attributes.holiday_name }}"
```

```yaml
# 学生假期推送通知
trigger:
  - platform: state
    entity_id: binary_sensor.智能工作日_学生假期
    to: "on"
action:
  - service: notify.mobile_app
    data:
      message: "🎉 今天是学生假期！"
```

```yaml
# 调休上班日提醒
trigger:
  - platform: time
    at: "07:00:00"
condition:
  - condition: template
    value_template: >-
      {{ is_state('binary_sensor.智能工作日_工作日', 'on')
         and states.binary_sensor.智能工作日_工作日.attributes.is_special_workday }}
action:
  - service: notify.mobile_app
    data:
      message: "⚠️ 今天是调休上班日，别睡过头！"
```

## 技术细节

### 项目结构

```
custom_components/smart_workday/
├── __init__.py          # 集成入口，Store 初始化 + YAML 迁移
├── const.py             # 常量、枚举定义
├── coordinator.py       # 数据协调器 + Store 持久化 + 日期分析
├── config_flow.py       # 配置流 + 选项流（JSON 高级编辑）
├── binary_sensor.py     # 3 个 boolean 实体（is_workday/is_holiday/is_student_holiday）
├── calendar.py          # 3 个日历实体（法定/学生/自定义，支持增删事件）
├── manifest.json        # 集成元数据
└── translations/        # 中英文翻译
```

### 判定逻辑

```
调休上班日？ → is_workday=True, is_special_workday=True
  ↓ 否
法定节假日 或 自定义假日？ → is_holiday=True
  ↓ 否
自然周末（周六/周日）？ → is_weekend=True
  ↓ 否
普通工作日 → is_workday=True
```

> 学生假期独立判断（`is_student_holiday`），不影响上述工作日/放假逻辑。

### 存储架构

- **持久化**: HA Store（JSON 格式，`.storage/` 目录）
- **缓存**: DataManager 内存缓存（1 分钟 TTL）
- **迁移**: 自动从旧版 `calendar.yaml` 迁移（仅首次）

## 更新日志

### v2.3.0
- ✨ 日历改为 3 个独立实体（法定节假日/学生假期/自定义假期），事件自动归类，无需切换
- ✨ 删除 `select.py` 假期类型下拉实体，日历即分类
- 🔧 移除 `HolidayType` 枚举，新增 `CalendarType` 枚举
- 🔧 移除 `ATTR_CURRENT_TYPE`、`HOLIDAY_TYPE_OPTIONS`、`HOLIDAY_TYPE_LABELS` 等 select 相关常量

### v2.2.0
- ✨ 删除 `sensor.py` 主实体，简化为 3 个独立 boolean：`is_workday` / `is_holiday` / `is_student_holiday`
- ✨ 详细信息（日期、星期、模式、是否调休、事件列表等）统一挂在 `is_workday` 实体属性中
- ✨ `is_holiday` / `is_student_holiday` 保持纯粹 boolean，无冗余属性
- 🔧 移除 `WorkdayState` 枚举、`STATE_ICONS`、`_STATE_NAMES`（不再需要 3 态）
- 🔧 `coordinator.DayInfo` 移除 `state` / `state_name` 字段
- 🔧 移除 translations 的 `state_names` 段

### v2.1.0
- ✨ 持久化从 YAML 文件迁移到 HA Store（`.storage/` JSON），升级不丢数据
- ✨ 实体状态简化为 3 态：工作日 / 节假日 / 双休日
- ✨ 新增 `is_workday` 二进制传感器（ON/OFF 供自动化用）
- 🔧 高级编辑改为 JSON 格式
- 🔧 `yaml_category` 重命名为 `data_category`
- 🔧 移除 `calendar.yaml` 和 `DEFAULT_YAML_TEMPLATE`
- 🔧 全部 Store 操作异步化

### v2.0.0
- ✨ 主实体改为 sensor，状态直接显示中文
- ✨ 日历面板支持直接增删假期
- ✨ 假期类型下拉实体（3 类：自定义/法定/学生）
- ✨ 调休合并进法定假日（名称含「调休」自动识别）
- 🔧 移除预设导入功能
- 🔧 全部实体启用 `has_entity_name`

## 许可证

MIT License
