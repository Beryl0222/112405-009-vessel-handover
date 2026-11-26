# 船岸交接 NLP 整理与下一班行动条件

> 本记录、船名、呼号与事件均为虚构演练资料。

案例：`vessel-5`；来源记录 3 条；可追溯句段 4 个；航迹哈希链校验：通过。

## 一、行动卡与当前阻断条件

### 🟡 现行指令，继续执行 维持现位 (`AC-V-2-maintain_position`)
- 船只：`V-2`；修订：2；状态：`in_force`
- 船长/指令表述：`CL-VH-5-03-A`
- 许可相关表述：`CL-VH-5-02-C`
- 无未满足的硬阻断条件。
- 提示/需继续观察：
  - 定位信号间歇/周期性丢失（时间关系未澄清） [VH-7 VH-7#S1]
  - 岸站确认/移锚许可 / shore confirmation or clearance（维持现位的终止条件：许可确认后转入下一判定） [VH-5 VH-5#S1] [VH-6 VH-6#S2]
- 追溯：[VH-5 VH-5#S1] [VH-7 VH-7#S1]

### ⛔ 被条件阻止 移锚 (`AC-V-2-shift_anchor`)
- 船只：`V-2`；修订：3；状态：`blocked`
- 船长/指令表述：`CL-VH-5-01-A`
- 岸站建议（非命令）：`CL-VH-6-01-A`
- 许可相关表述：`CL-VH-6-02-C`
- **仍被以下条件阻止：**
  - `authorization.shore_clearance` 岸站确认/作业许可已签发并收到：**明确未具备** [VH-5 VH-5#S1] [VH-6 VH-6#S2]
  - `weather.wind_east` 风转东 / wind turns east：**待满足** [VH-5 VH-5#S1]
- 提示/需继续观察：
  - 定位信号间歇/周期性丢失（时间关系未澄清） [VH-7 VH-7#S1]
  - 当前阵风过去 / current gust passes [VH-6 VH-6#S1]
- 追溯：[VH-5 VH-5#S1] [VH-6 VH-6#S1] [VH-6 VH-6#S2] [VH-7 VH-7#S1]

## 二、谁报告了什么

- [VH-5 VH-5#S1] **船长**（记录渠道：船长）[条件句] 船长条件性指令：移锚 / shift anchor。
  - 原句：“风转东后再移锚，未收到岸站确认前维持现位。”
- [VH-5 VH-5#S1] **船长**（记录渠道：船长）[状态说明] 明确说明岸站确认/许可尚未收到或尚未签发。
  - 原句：“风转东后再移锚，未收到岸站确认前维持现位。”
- [VH-5 VH-5#S1] **船长**（记录渠道：船长）[条件句] 船长条件性指令：维持现位 / maintain position。
  - 原句：“风转东后再移锚，未收到岸站确认前维持现位。”
- [VH-6 VH-6#S1] **岸站**（记录渠道：无线电/值班报务）[条件句] 岸站建议/提议 移船/移动（需上下文指代）。
  - 原句：“Shore suggests moving after the current gust;”
- [VH-6 VH-6#S2] **无线电/值班报务**（记录渠道：无线电/值班报务）[状态说明] 明确说明岸站确认/许可尚未收到或尚未签发。
  - 原句：“no clearance has been issued.”

## 三、海况/天气及适用条件

### 行动卡引用的海况条件
- `weather.gust_passed` 当前阵风过去 / current gust passes：**待满足**（建议性）[VH-6 VH-6#S1]
- `weather.wind_east` 风转东 / wind turns east：**待满足**（指令要求）[VH-5 VH-5#S1]

### 数值/定性观测
- 未提取到数值或定性海况记录。

## 四、设备状态及时序

- 定位信号间歇/周期性丢失：`intermittent`；与移锚的时间先后未澄清；细节：每隔几分钟丢一次 [VH-7 VH-7#S1]

## 五、传给下一班的确认条件

### 已确认/已满足，可继续引用
- `authority.captain_order` 船长命令（岸站建议/转译不能替代） [VH-5 VH-5#S1]

### 未满足，继续阻止行动
- `authorization.shore_clearance` 岸站确认/移锚许可 / shore confirmation or clearance：**明确未具备** [VH-5 VH-5#S1] [VH-6 VH-6#S2]
- `weather.wind_east` 风转东 / wind turns east：**待满足** [VH-5 VH-5#S1]

### 下一班动作
- 继续：维持现位 (`AC-V-2-maintain_position`)
- 不得启动：移锚 (`AC-V-2-shift_anchor`)；待解除：岸站确认/作业许可已签发并收到、风转东 / wind turns east

## 六、冲突、歧义和审计提示

- **信息** `equipment_timing_unknown`：设备异常仅有间歇/丢失报告，尚未记录其与移锚的时间先后。 [VH-7 VH-7#S1]
- **信息** `contextual_action_coreference`：“moving/移动”按同船唯一已知移锚事项指代到移锚；该关联保留原句证据。 [VH-6 VH-6#S1]

## 七、追溯方式

- 每条主张、条件、观察和行动卡均带 `record_id`、`sentence_id` 与原句引文/字符范围。
- 调用 `store.trace('<record-id>#S1')` 可反查引用该句的全部判断。
- 新日志应使用新的记录编号；来源记录和哈希链航迹记录均不可覆盖。
