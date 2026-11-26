# 多语船岸交接 NLP 与续班行动判定

这是一个无需第三方运行依赖的 Python 3.11+ 项目，用于持续整理由**中文、英语和无线电简写**组成的远洋调查船船岸交接文本。所有船名、呼号、记录、许可、航迹和事件均为虚构演练资料，不对应真实人员、机构、地点或业务决定。

它不是把多条日志压缩成一条“摘要结论”，而是保留：

（基线案例的生成样式见 [`examples/sample_brief.md`](examples/sample_brief.md)。）

- **谁通过什么渠道报告了什么**；
- 原句、句段编号和字符范围，支持从判断反查原文；
- 船长命令、岸站建议、转译声称、许可状态之间的区别；
- 条件句中的待满足条件，不把“等风转东后……”改写成无条件许可；
- 天气/海况、定位设备状态及其相对于移锚的时间关系；
- 可连续摄入新日志的行动卡：未完成卡片重新判定，已完成航迹哈希归档且不可改写；
- 下一班应继续做什么、不得做什么、哪些条件已经确认。

## 快速运行

```sh
python3 -m unittest discover -s tests -v

# 也可使用 python3 main.py ... 作为下面 CLI 的等价入口
# 从 data/case.json 生成结构化状态和中文 Markdown 简报
python3 -m voyage_handover build data/case.json \
  --store output/store.json \
  --brief output/brief.md \
  --json output/full-analysis.json

# 反查某个原句产生了哪些判断
python3 -m voyage_handover trace --store output/store.json VH-7#S1
```

也可安装为命令：

```sh
python3 -m pip install -e .
voyage-handover build data/case.json --brief brief.md
```

## 持续摄入新日志

来源记录采用追加式存储。新澄清必须使用新的记录编号；覆盖旧 `id` 的内容会抛出
`ImmutableRecordError`。结构化航迹点进入哈希链，改写会抛出 `ImmutableTrackError`。

```sh
# 初始案例
python3 -m voyage_handover build data/case.json --store output/example-store.json

# 一条“已批准”的转译：仍不会被当成真实许可
python3 -m voyage_handover ingest --store output/example-store.json \
  examples/stage1_translation.json

# 随后收到真实许可并观测到风转东：移锚卡才可能转为 ready
python3 -m voyage_handover ingest --store output/example-store.json \
  examples/stage2_clearance_weather.json \
  --brief output/example-brief.md

# 新日志澄清设备异常发生在移锚前
python3 -m voyage_handover ingest --store output/example-store.json \
  examples/stage3_timing_before.json

# 完成航迹可单独追加；之后该移锚卡保持 completed，不被重新判定为未完成
python3 -m voyage_handover ingest --store output/example-store.json \
  examples/completed_track.json

python3 -m voyage_handover verify --store output/example-store.json
```

## Python API

```python
from voyage_handover import HandoverStore, render_markdown

case = {
    "case_id": "vessel-5",
    "vessels": [
        {"id": "V-2", "callsign": "HAI-5", "aliases": ["海五", "调查五号"]}
    ],
    "records": [
        {
            "id": "VH-5",
            "kind": "captain-note",
            "lang": "zh",
            "text": "风转东后再移锚，未收到岸站确认前维持现位。",
        },
        {
            "id": "VH-6",
            "kind": "radio-summary",
            "lang": "en",
            "text": "Shore suggests moving after the current gust; no clearance has been issued.",
        },
        {
            "id": "VH-7",
            "kind": "equipment-note",
            "lang": "zh",
            "text": "定位每隔几分钟丢一次，时间未记录。",
        },
    ],
}

store = HandoverStore.from_case(case)
anchor = next(c for c in store.action_cards.values() if c.action_key == "shift_anchor")

print(anchor.status)          # blocked
print(anchor.blocker_keys)    # ['authorization.shore_clearance', 'weather.wind_east']
print(render_markdown(store.briefing()))

# 新记录到达后重新判定未完成卡片
store.ingest_record({
    "id": "VH-8",
    "kind": "shore-message",
    "text": "岸站已签发移锚许可 CLR-77。",
})
store.ingest_record({
    "id": "VH-9",
    "kind": "captain-log",
    "text": "18:10 风已转东。",
})
anchor = next(c for c in store.action_cards.values() if c.action_key == "shift_anchor")
print(anchor.status)          # ready（卡片 ID 稳定，对象已在重算后替换）

# 沿原句追溯
print(store.trace("VH-5#S1"))
```

## 判定规则概览

### 行动卡状态

| 状态 | 含义 |
| --- | --- |
| `blocked` | 至少一个硬条件未满足，不得启动 |
| `in_force` | 现行指令仍须执行，例如“维持现位” |
| `ready` | 船长命令、许可和必要条件均有肯定证据，可提交值班指挥决策 |
| `completed` | 有完成记录或航迹事件；卡片归档，不回退为未完成 |
| `ambiguous` | 船名/呼号被多个船只复用且缺少 `vessel_id` 或时效上下文，不能猜船 |

### 关键条件键

- `authority.captain_order`：必须有船长/本船命令；岸站 `suggest/recommend/建议` 只进入 `suggestion_claim_ids`。
- `authorization.shore_clearance`：岸站确认/许可。`no clearance ... issued`、`CLR NIL`、`未收到确认` 为 `absent`；真实肯定签发记录才可为 `met`。
- `weather.wind_east`：船长指定的“风转东”条件。
- `weather.gust_passed`：岸站建议中的阵风条件，默认作为建议性观察，不替代船长的风向东条件。
- `equipment.positioning_normal` / 设备观察：间歇、丢失、恢复及时序。默认策略下，定位丢失硬阻止移锚；间歇定位对移锚为安全提示，但硬阻止测量/作业开始。可通过 `policy` 调整。
- `equipment.timing_verified`：当策略 `block_on_untimed_abnormal_positioning=True` 且异常时间关系不明时启用。

### 转译和条件句审计

如果转译/摘要出现“已批准 / approved now”，但原始记录仍有：

- 条件标记（`后再`、`等`、`after`、`once`、`before` 等）；或
- `no clearance issued` / `未收到确认` / `CLR NIL`；

系统会：

1. 保留该转译主张，但标记为 `translated_clearance_claim` / `translated_approval_claim`；
2. 不把它作为权威许可满足 `authorization.shore_clearance`；
3. 产生 `unverified_translation_as_clearance` 警告；
4. 若行动卡因此可能被误放行，产生阻断级 `conditional_permission_flattened` 审计问题。

### 复用船名/呼号

`VesselRegistry` 会索引船只 `id`、`callsign` 和 `aliases`。当同一呼号对应多艘船时：

- 记录显式提供 `"vessel_id": "V-NEW"` 时优先；
- 或船只登记 `valid_from` / `valid_to` 且记录有时间戳时，按有效期选择；
- 否则返回 `ambiguous_reused_identifier`，行动卡为 `ambiguous`，不猜测归属。

## 持久化与不可改写

`HandoverStore.save(path)` 输出完整 JSON：来源记录、句段索引、主张、观察、条件状态历史、行动卡、问题、航迹哈希链和简报。`HandoverStore.load(path)` 会从追加式来源记录重建投影。

- 相同 `id` + 相同内容重复摄入是幂等操作；
- 相同 `id` 但内容变化：`ImmutableRecordError`；
- 航迹记录使用内容 SHA-256 和链式 `chain_hash`，可用 `verify_track_chain()` 校验；
- 新的时间澄清不会删除旧的“时间未记录”观察；旧证据保留，当前卡片使用最新证据重新判定。

## 代码结构

- `voyage_handover/pipeline.py`：多语句切分、说话人/行动/条件/设备/海况/时序规则抽取。
- `voyage_handover/entities.py`：船只别名、呼号复用和时效消歧。
- `voyage_handover/models.py`：证据、主张、条件、观察、行动卡数据结构。
- `voyage_handover/store.py`：追加日志、条件合并、行动卡重判、航迹哈希链和持久化。
- `voyage_handover/briefing.py`：下一班交接包与中文 Markdown。
- `voyage_handover/cli.py`：`build`、`ingest`、`show`、`trace`、`verify` 命令。
- `tests/test_handover.py`：覆盖题述主场景、增量澄清、不可改写、呼号复用、简写和追溯。

规则词表位于 `voyage_handover/lexicon.py`，可继续补充新的简写、设备名、海况表达或说话人头衔。
