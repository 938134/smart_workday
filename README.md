# Smart Workday 智能工作日

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Version](https://img.shields.io/badge/version-2.8.0-blue)]()
[![HA](https://img.shields.io/badge/HA-2023.9%2B-orange)]()

Home Assistant 自定义集成，智能判断当天是否为工作日，支持法定假期、学生假期和自定义假期。

## 功能特点

- **1 个日历** — 所有假期合并到一个日历，事件描述自动标注来源
- **4 个 boolean 实体** — `is_workday` / `is_holiday` / `is_student_holiday` / `is_custom_holiday`，自动化直接用 ON/OFF
- **顶层 3 开关** — 法定/学生/自定义假期可独立启用或禁用
- **一键导入** — 支持从国务院通知一键填充 2026 年法定假期
- **调休自动识别** — 名称含「调休」自动归为上班日
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

1. 设置 → 设备与服务 → 添加集成 → 搜索 "Smart Workday"
2. 输入集成名称，勾选要启用的假期类型
3. （可选）勾选「立即导入」一键填充 2026 年国务院法定假期
4. 提交后自动进入选项配置，可直接完成
5. 假期条目的日常增删通过**日历实体**完成（支持 CREATE/DELETE_EVENT）

## 生成的实体

### 4 个 boolean 二进制传感器

| 实体 | 状态 | 说明 |
|------|------|------|
| `is_workday` | ON/OFF | 是否工作日（含调休上班）；**承载所有详细信息属性** |
| `is_holiday` | ON/OFF | 是否法定节假日（不含调休、不含自定义） |
| `is_student_holiday` | ON/OFF | 是否学生假期（独立标志位，不影响工作日） |
| `is_custom_holiday` | ON/OFF | 是否自定义假期（独立标志位，不影响工作日） |

### 1 个日历

`假期日历` — 显示所有类型的假期事件，事件描述标注来源：
- 📅 法定假期
- 💼 调休上班日
- 🎓 学生假期
- ⭐ 自定义假期

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

> 学生假期（`is_student_holiday`）和自定义假期（`is_custom_holiday`）是**独立标志位**，不影响工作日判定。

## 配置管理

### 修改顶层开关

设置 → 设备与服务 → Smart Workday → 配置 → 切换开关 → 保存（自动 reload）

### 重新导入法定假期

配置 → 勾选「立即导入」→ 选择年份 → 保存（会覆盖当前法定假期数据）

### 增删假期条目

通过**日历实体**完成：

- **添加**：点击日期 → 填写名称 → 保存
  - 名称含「调休」→ 归为调休上班日
  - 名称含「寒假/暑假/春假/秋假/儿童节/学生」→ 归为学生假期
  - 其他 → 归为自定义假期
- **删除**：点击事件 → 删除

## 数据格式

数据存储在 HA 的 `.storage/smart_workday.<entry_id>` 文件（JSON 格式）：

```json
{
  "holidays": [
    {"name": "元旦", "date": "2026-01-01", "uid": "abc12345"},
    {"name": "春节", "start": "2026-02-17", "end": "2026-02-23", "uid": "def67890"},
    {"name": "春节调休上班", "date": "2026-02-14", "uid": "ghi11111"}
  ],
  "customdays": [
    {"name": "植树节", "date": "2026-03-12", "uid": "jkl22222"}
  ],
  "studentdays": [
    {"name": "暑假", "start": "2026-07-10", "end": "2026-08-31", "uid": "mno33333", "enabled": true}
  ]
}
```

> ⚠️ **注意**：学生假期和自定义假期不影响工作日判定，只触发独立传感器。

### 从旧版 YAML 迁移

从 v2.0.0 升级时，集成会自动检测旧版 `calendar.yaml` 文件并迁移数据到 Store。无需手动操作。

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
# 自定义假期推送（如结婚纪念日）
trigger:
  - platform: state
    entity_id: binary_sensor.智能工作日_自定义假期
    to: "on"
action:
  - service: notify.mobile_app
    data:
      message: "⭐ 今天是自定义纪念日！"
```

## 技术细节

### 项目结构

```
custom_components/smart_workday/
├── __init__.py          # 集成入口，Store 初始化 + YAML 迁移 + 导入标记处理
├── const.py             # 所有常量（版本号唯一权威来源）
├── coordinator.py       # 数据协调器 + Store 持久化 + 日期分析
├── config_flow.py       # ConfigFlow（1 步）+ OptionsFlow（1 步）
├── binary_sensor.py     # 4 个 boolean 实体
├── calendar.py          # 1 个日历实体（支持 CREATE/DELETE_EVENT）
├── manifest.json        # 集成元数据
└── translations/        # 中英文翻译
```

### 存储架构

- **持久化**: HA Store（JSON 格式，`.storage/` 目录）
- **缓存**: DataManager 内存缓存（1 分钟 TTL）
- **迁移**: 自动从旧版 `calendar.yaml` 迁移（仅首次）

## 更新日志

### v2.8.0
- ✨ **重度简化**：ConfigFlow/OptionsFlow 均改为 1 步（原来 12+ 步）
- ✨ **删除所有子步骤**：route/legal/student/custom 及其 add/delete/clear/import 子步骤全部移除
- ✨ **日历 UI 统一编辑**：所有假期增删统一通过日历实体完成（CREATE/DELETE_EVENT）
- ✨ **常量集中管理**：新增 `DOMAIN_DISPLAY_NAME` / `DEFAULT_LEGAL_YEAR` / `CALENDAR_ENTITY_NAME` / `CALENDAR_MODEL` / `SENSOR_MODEL` / `STUDENT_HOLIDAY_KEYWORDS` / `MAKEUP_KEYWORD`
- 🔧 删除死代码：`ENABLED_TO_CATEGORY`、`StudentHolidayType`、`STUDENT_HOLIDAY_DEFAULTS`、`_STUDENT_HOLIDAY_NAMES`
- 🔧 `STORAGE_VERSION` 从 coordinator.py 挪到 const.py 统一管理
- 🔧 消除所有硬编码字符串（"Smart Workday" / "智能工作日" / "2026" 只在 const.py 出现）

### v2.7.0
- ✨ 全局改名：「法定节假日」→「法定假期」
- ✨ ConfigFlow 新增 `import_legal` + `import_legal_year` 一键导入
- 🔧 删除 OptionsFlow `async_step_advanced`（JSON 编辑器）

### v2.6.0
- ✨ 版本号统一维护（`const.VERSION`）
- ✨ 删除 `HolidayMode` 枚举（标准/自由模式）
- ✨ 简化判定逻辑：双休 + 法定为主，学生/自定义为独立标志位
- ✨ 新增 `is_custom_holiday` 传感器

### v2.5.0
- ✨ 两步式 Flow + 顶层 3 开关
- ✨ 单日历合并所有类型（description 区分来源）
- 🔧 判定逻辑修正

### v2.4.0
- ✨ 完整 UI 化 Options Flow（13 步）

### v2.3.0
- ✨ 日历改为 3 个独立实体

### v2.2.0
- ✨ 删除 sensor.py，简化为 3 个独立 boolean

### v2.1.0
- ✨ 持久化从 YAML 迁移到 HA Store（`.storage/` JSON）

### v2.0.0
- ✨ 主实体改为 sensor，日历面板支持直接增删

## 许可证

MIT License
