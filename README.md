# Smart Workday 智能工作日

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Version](https://img.shields.io/badge/version-3.1.0-blue)]()
[![HA](https://img.shields.io/badge/HA-2023.9%2B-orange)]()

Home Assistant 自定义集成，智能判断当天是否为工作日，支持法定假期和带类别的自定义假期。

## 功能特点

- **2 个设备** — 传感器设备（工作日 + 假期日历）+ 诊断设备（法定假期 + 自定义假期）
- **3 个 boolean 实体** — `is_workday` / `is_holiday` / `is_custom_holiday`，自动化直接用 ON/OFF
- **4 个开关** — 传感器 2 个（工作日 / 假期日历）+ 诊断 2 个（法定假期 / 自定义假期）
- **chinese-calendar 自动导入** — 自动导入当年国务院法定假期，每年 11 月库更新即可用
- **调休自动识别** — 名称含「调休」自动归为上班日
- **带类别的自定义假期** — 下拉选类别（学生 / 工作 / 个人 / 家庭）或自定义输入
- **日历详细状态** — 显示进行中 / 空闲状态、当前事件、未来事件、数据统计
- **Store 持久化** — 数据存储在 HA 标准 `.storage/` 目录，升级不丢失
- **v1→v2 自动迁移** — 老 Store 结构自动无损迁移到新结构

## 安装

### HACS（推荐）

1. HACS → 集成 → 右上角菜单 → 自定义仓库
2. 添加仓库：`https://github.com/938134/smart-workday`
3. 搜索 "Smart Workday" 并安装

### 手动安装

将 `custom_components/smart_workday` 文件夹复制到 HA 的 `custom_components` 目录，重启 HA。

## 快速开始

1. 设置 → 设备与服务 → 添加集成 → 搜索 "Smart Workday"
2. 输入集成名称（开关在选项页面配置）
3. 提交后自动进入选项配置页面
4. 开关管理：控制传感器 / 诊断实体的可见性
5. 添加假期：下拉选类别（学生 / 工作 / 个人 / 家庭，或输入新类别）+ 名称 + 日期
6. 假期条目的日常增删通过**日历实体**完成（支持 DELETE_EVENT）

## 生成的实体

### 传感器设备（2 个实体）

| 实体 | 状态 | 说明 |
|------|------|------|
| `工作日` | ON/OFF | 是否工作日（含调休上班）；**承载所有详细信息属性** |
| `假期日历` | ON/OFF | 日历实体，显示所有假期事件 |

### 诊断设备（2 个实体）

| 实体 | 状态 | 说明 |
|------|------|------|
| `法定假期` | ON/OFF | 今天是否法定节假日 |
| `自定义假期` | ON/OFF | 今天是否有自定义假期 |

### 日历详细状态

假期日历实体的 `attributes` 包含：

| 属性 | 说明 |
|------|------|
| `state` | 进行中 / 空闲 / 无假期 |
| `current_event` | 当前进行中的事件名称 |
| `current_event_end` | 当前事件结束日期 |
| `upcoming` | 未来 7 天最多 5 个事件（name / date / days_until） |
| `legal_count` | 法定假期数据条目数 |
| `custom_count` | 自定义假期数据条目数 |

## 工作日判定逻辑

```
调休上班日？ → is_workday=True, is_special_workday=True（即使周末）
  ↓ 否
法定假期 + 周六同天？ → is_holiday=True + is_weekend=True（并列）
  ↓ 否
自然周末（周六/周日）？ → is_weekend=True
  ↓ 否
普通工作日 → is_workday=True
```

> 法定假期（`is_holiday`）和自定义假期（`is_custom_holiday`）是**独立标志位**，不影响工作日判定。

## 配置管理

### 开关管理（2 段 4 个开关）

设置 → 设备与服务 → Smart Workday → 配置 → 开关管理

**传感器段**：
- 💼 工作日 — 今天是否工作日
- 📆 假期日历 — 日历实体

**诊断段**：
- 📅 法定假期 — 今天是否法定假期
- 🎉 自定义假期 — 今天是否有自定义假期

### 添加假期

配置 → 添加假期：
- 类别：下拉选（学生 / 工作 / 个人 / 家庭）或输入新类别
- 名称：假期名称
- 开始日期 / 结束日期（留空为单日）

### 删除假期条目

通过**日历实体**完成：点击事件 → 删除

## 数据格式

数据存储在 HA 的 `.storage/smart_workday.<entry_id>` 文件（JSON 格式）：

```json
{
  "legal": [
    {"name": "元旦", "date": "2026-01-01", "uid": "abc12345"},
    {"name": "春节", "start": "2026-02-17", "end": "2026-02-23", "uid": "def67890"},
    {"name": "春节调休上班", "date": "2026-02-14", "uid": "ghi11111"}
  ],
  "custom": [
    {"name": "寒假", "start": "2026-01-15", "end": "2026-02-10", "uid": "jkl22222", "category": "学生"},
    {"name": "出差", "date": "2026-03-12", "uid": "mno33333", "category": "工作"}
  ]
}
```

### 旧版自动迁移

从 v2.x 升级时，集成自动无损迁移：
- `holidays` → `legal`（原样）
- `studentdays` → `custom`，每条加 `category="学生"`
- `customdays` → `custom`，每条加 `category="自定义"`

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
# 调休上班日提醒（别睡过头）
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

```yaml
# 法定节假日推送
trigger:
  - platform: state
    entity_id: binary_sensor.智能工作日_法定假期
    to: "on"
action:
  - service: notify.mobile_app
    data:
      message: "🎊 今天是法定节假日！{{ states.binary_sensor.智能工作日_工作日.attributes.holiday_name }}"
```

```yaml
# 自定义假期推送（检查 active_custom 属性）
trigger:
  - platform: state
    entity_id: binary_sensor.智能工作日_自定义假期
    to: "on"
action:
  - service: notify.mobile_app
    data:
      message: >-
        ⭐ 今天有自定义假期！
        类别：{{ states.binary_sensor.智能工作日_自定义假期.attributes.active_custom | tojson }}
```

## 技术细节

### 项目结构

```
custom_components/smart_workday/
├── __init__.py          # 集成入口，Store 初始化 + v1→v2 迁移 + 法定假期自动导入
├── const.py             # 所有常量（版本号唯一权威来源）
├── coordinator.py       # 数据协调器 + Store 持久化 + 日期分析（DayInfo）
├── config_flow.py       # ConfigFlow（1 步）+ OptionsFlow（init/toggle_switch/add_holiday/finish）
├── binary_sensor.py     # 3 个 boolean 实体（分属传感器 + 诊断 2 个设备）
├── calendar.py          # 1 个日历实体（支持 DELETE_EVENT + 详细状态属性）
├── manifest.json        # 集成元数据
└── translations/        # 中英文翻译
```

### 存储架构

- **持久化**: HA Store（JSON 格式，`.storage/` 目录）
- **缓存**: DataManager 内存缓存
- **迁移**: v1 Store 结构自动无损迁移（首次启动时检测）
- **依赖**: `chinese-calendar>=1.11.0`（法定假期数据源）

## 更新日志

### v3.1.0
- ✨ **设备分区**：实体按 2 个设备分区（传感器 + 诊断）
  - 传感器设备：假期日历 + 工作日
  - 诊断设备：法定假期 + 自定义假期
- ✨ **日历详细状态**：`attributes` 含进行中/空闲、当前事件、未来事件、数据统计
- ✨ **4 个实体开关**：传感器 2 个 + 诊断 2 个，独立控制实体可见性
- 🔧 常量清理：移除废弃的 diag 常量

### v3.0.0
- ✨ **破坏性重构**：Store 结构从 3 分类（holidays/studentdays/customdays）合并为 2 分类（legal/custom）
- ✨ **带类别的自定义假期**：每条 custom 条目带 `category` 字段（学生/工作/个人/家庭/自定义...）
- ✨ **合并 add_student + add_custom** 为单一 add_holiday 步骤
- ✨ **v1→v2 自动迁移**：老数据无损迁移，uid 保留
- 🔧 删除 `is_student_holiday` 传感器（学生假期归入自定义假期 + 类别）
- 🔧 删除 `enabled_student` 开关
- 🔧 DayInfo 新增 `active_custom: Dict[str, List[str]]`

### v2.20.0
- ✨ **chinese-calendar 自动导入**：改用 `chinese-calendar` 库替代硬编码 LEGAL_HOLIDAY_PRESETS
- 🔧 删除 37 行硬编码假数据，运行时从库读取

### v2.19.0
- 🔧 `load_calendar_data` 用 `setdefault` 补齐缺失字段，修复写入活动后传感器不可用
- 🔧 清理冗余代码：`sensor_key`、`_attr_should_poll`、实体级 `_attr_sw_version`
- 🔧 假期日历事件 summary 加日期范围（`国庆节 (10-01~10-08)`）

### v2.18.7
- ✨ 代码审查：修复 6 类问题（死代码、硬编码、跨类访问、状态冗余等）

## 许可证

MIT License
