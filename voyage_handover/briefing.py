"""Watch-officer briefing and Markdown rendering."""

from __future__ import annotations

from typing import Any

from .lexicon import ROLE_LABELS_ZH

STATUS_ZH = {
    "blocked": "⛔ 被条件阻止",
    "ready": "✅ 条件已确认",
    "completed": "⚓ 已完成并归档",
    "ambiguous": "❓ 船只归属歧义",
    "cancelled": "已取消",
    "in_force": "🟡 现行指令，继续执行",
}

STATE_ZH = {
    "required": "待满足",
    "met": "已确认/已满足",
    "absent": "明确未具备",
    "unknown": "状态待核实",
    "conflicting": "证据冲突",
    "not_applicable": "不适用",
}

SEVERITY_ZH = {"blocker": "阻断", "warning": "警告", "info": "信息"}


def _ev_dict(evidence: Any) -> dict[str, Any]:
    if hasattr(evidence, "to_dict"):
        return evidence.to_dict()
    return dict(evidence)


def evidence_ref(evidence: Any) -> str:
    item = _ev_dict(evidence)
    sid = item.get("sentence_id")
    return f"[{item.get('record_id')}{' ' + sid if sid else ''}]"


def unique_refs(refs: list[str]) -> list[str]:
    return list(dict.fromkeys(refs))


def evidence_line(evidence: Any) -> str:
    item = _ev_dict(evidence)
    quote = (item.get("quote") or "").strip().replace("\n", " ")
    return f"{evidence_ref(item)} “{quote}”"


def _condition_view(condition: Any) -> dict[str, Any]:
    data = condition.to_dict() if hasattr(condition, "to_dict") else dict(condition)
    data["state_zh"] = STATE_ZH.get(data.get("state"), data.get("state"))
    refs = [evidence_ref(e) for e in data.get("state_evidence", []) or data.get("requirement_evidence", [])]
    if not refs:
        refs = [evidence_ref(e) for e in data.get("requirement_evidence", [])]
    data["evidence_refs"] = unique_refs(refs)
    return data


def build_briefing(store: Any) -> dict[str, Any]:
    """Build the next-watch hand-over packet from a :class:`HandoverStore`."""

    who_reported_what: list[dict[str, Any]] = []
    for claim in sorted(store.claims.values(), key=lambda c: str(c.id)):
        who_role = claim.speaker_role if claim.speaker_role != "unknown" else claim.reporter_role
        who_reported_what.append(
            {
                "claim_id": claim.id,
                "who_role": who_role,
                "who": ROLE_LABELS_ZH.get(who_role, who_role),
                "speaker_role": claim.speaker_role,
                "reporter_role": claim.reporter_role,
                "reporter": ROLE_LABELS_ZH.get(claim.reporter_role, claim.reporter_role),
                "what": claim.summary,
                "kind": claim.kind,
                "speech_act": claim.speech_act,
                "modality": claim.modality,
                "polarity": claim.polarity,
                "action_key": claim.action_key,
                "action_label": claim.action_label,
                "vessel_id": claim.vessel.vessel_id if claim.vessel else None,
                "vessel_resolution": claim.vessel.resolution if claim.vessel else None,
                "record_id": claim.record_id,
                "sentence_id": claim.sentence_id,
                "provenance": [_ev_dict(e) for e in claim.evidence],
                "provenance_refs": unique_refs([evidence_ref(e) for e in claim.evidence]),
            }
        )

    equipment_status = [o.to_dict() for o in store.observations.values() if o.category == "equipment"]
    sea_state = [o.to_dict() for o in store.observations.values() if o.category in {"weather", "sea_state"}]

    action_cards: list[dict[str, Any]] = []
    blocked_actions: list[dict[str, Any]] = []
    ready_actions: list[dict[str, Any]] = []
    active_instructions: list[dict[str, Any]] = []
    completed_actions: list[dict[str, Any]] = []

    for card in sorted(store.action_cards.values(), key=lambda c: c.id):
        card_data = card.to_dict()
        blocker_details = [
            _condition_view(card.conditions[key])
            for key in card.blocker_keys
            if key in card.conditions
        ]
        advisory_details: list[dict[str, Any]] = []
        for key in card.advisory_keys:
            if key in card.conditions:
                advisory_details.append(_condition_view(card.conditions[key]))
            elif key in store.observations:
                obs = store.observations[key]
                advisory_details.append(
                    {
                        "key": key,
                        "category": "equipment",
                        "label": obs.label,
                        "state": obs.state,
                        "temporal_relation": obs.temporal_relation,
                        "evidence_refs": unique_refs([evidence_ref(e) for e in obs.evidence]),
                    }
                )
        card_data["status_zh"] = STATUS_ZH.get(card.status, card.status)
        card_data["blocker_details"] = blocker_details
        card_data["advisory_details"] = advisory_details
        card_data["provenance_refs"] = unique_refs([evidence_ref(e) for e in card.evidence])
        action_cards.append(card_data)

        summary = {
            "card_id": card.id,
            "title": card.title,
            "action_key": card.action_key,
            "vessel_id": card.vessel_id,
            "status": card.status,
            "status_zh": STATUS_ZH.get(card.status, card.status),
            "blockers": [
                {
                    "key": item["key"],
                    "label": item["label"],
                    "state_zh": item["state_zh"],
                    "evidence_refs": item["evidence_refs"],
                }
                for item in blocker_details
            ],
            "advisories": [
                {
                    "key": item.get("key"),
                    "label": item.get("label"),
                    "state_zh": item.get("state_zh", item.get("state")),
                    "evidence_refs": item.get("evidence_refs", []),
                }
                for item in advisory_details
            ],
            "provenance_refs": card_data["provenance_refs"],
        }
        if card.status == "blocked":
            blocked_actions.append(summary)
        elif card.status == "ready":
            ready_actions.append(summary)
        elif card.status == "in_force":
            active_instructions.append(summary)
        elif card.status == "completed":
            completed_actions.append(summary)

    confirmed_conditions = {
        condition.key: _condition_view(condition)
        for condition in sorted(store.conditions.values(), key=lambda c: c.key)
        if condition.state == "met"
    }
    for card in store.action_cards.values():
        for key, condition in sorted(card.conditions.items()):
            if condition.state == "met" and key not in confirmed_conditions:
                view = _condition_view(condition)
                view["action_card_id"] = card.id
                confirmed_conditions[key] = view

    unresolved_conditions = [
        _condition_view(condition)
        for condition in sorted(store.conditions.values(), key=lambda c: c.key)
        if condition.blocking and condition.state != "met"
    ]
    sea_conditions = [
        _condition_view(condition)
        for condition in sorted(store.conditions.values(), key=lambda c: c.key)
        if condition.category in {"weather", "sea_state"}
    ]

    issues = [issue.to_dict() for issue in store.all_issues()]
    next_watch = {
        "continue_instructions": active_instructions,
        "do_not_start_until_unblocked": blocked_actions,
        "ready_for_command_decision": ready_actions,
        "completed_do_not_rewrite": completed_actions,
        "confirmed_conditions": list(confirmed_conditions.values()),
        "unresolved_blocking_conditions": unresolved_conditions,
        "sea_conditions": sea_conditions,
        "equipment_watch": equipment_status,
        "sea_state_watch": sea_state,
        "handoff_rule": (
            "只可把 state=met 的条件作为已确认条件下传；required/absent/unknown/conflicting "
            "条件必须继续阻止对应行动。岸站建议和转译批准均不能替代船长命令或岸站许可。"
        ),
    }

    return {
        "case_id": store.case_id,
        "title": "船岸交接 NLP 整理与下一班行动条件",
        "fictional_data_notice": "本记录、船名、呼号与事件均为虚构演练资料。",
        "source_record_count": len(store.records),
        "sentence_count": len(store.sentences),
        "track_chain_verified": store.verify_track_chain(),
        "who_reported_what": who_reported_what,
        "action_cards": action_cards,
        "blocked_actions": blocked_actions,
        "ready_actions": ready_actions,
        "active_instructions": active_instructions,
        "completed_actions": completed_actions,
        "equipment_status": equipment_status,
        "sea_state": sea_state,
        "sea_conditions": sea_conditions,
        "issues": issues,
        "next_watch": next_watch,
        "provenance": {
            "mode": "every_claim_and_card_has_evidence",
            "sentence_lookup": "HandoverStore.trace('<record-id>#S<n>')",
            "sentences": list(store.sentences.values()),
        },
    }


def render_markdown(briefing: dict[str, Any]) -> str:
    """Render a structured briefing dictionary as Markdown."""

    lines: list[str] = []
    lines.append(f"# {briefing.get('title', '船岸交接简报')}")
    lines.append("")
    lines.append(f"> {briefing.get('fictional_data_notice', '')}")
    lines.append("")
    lines.append(
        f"案例：`{briefing.get('case_id')}`；来源记录 {briefing.get('source_record_count')} 条；"
        f"可追溯句段 {briefing.get('sentence_count')} 个；"
        f"航迹哈希链校验：{'通过' if briefing.get('track_chain_verified') else '无航迹/未通过'}。"
    )
    lines.append("")

    lines.append("## 一、行动卡与当前阻断条件")
    lines.append("")
    if not briefing.get("action_cards"):
        lines.append("未识别到行动卡。")
    for card in briefing.get("action_cards", []):
        lines.append(f"### {card.get('status_zh')} {card.get('title')} (`{card.get('id')}`)")
        vessel = card.get("vessel_id") or ("歧义候选: " + ", ".join(card.get("vessel_candidates", [])) if card.get("vessel_candidates") else "未解析")
        lines.append(f"- 船只：`{vessel}`；修订：{card.get('revision')}；状态：`{card.get('status')}`")
        if card.get("order_claim_ids"):
            lines.append(f"- 船长/指令表述：{', '.join(f'`{x}`' for x in card['order_claim_ids'])}")
        if card.get("suggestion_claim_ids"):
            lines.append(f"- 岸站建议（非命令）：{', '.join(f'`{x}`' for x in card['suggestion_claim_ids'])}")
        if card.get("clearance_claim_ids"):
            lines.append(f"- 许可相关表述：{', '.join(f'`{x}`' for x in card['clearance_claim_ids'])}")
        blockers = card.get("blocker_details", [])
        if blockers:
            lines.append("- **仍被以下条件阻止：**")
            for condition in blockers:
                refs = " ".join(condition.get("evidence_refs", []))
                lines.append(
                    f"  - `{condition.get('key')}` {condition.get('label')}："
                    f"**{condition.get('state_zh')}** {refs}"
                )
        elif card.get("status") == "blocked":
            lines.append("- 状态为 blocked，但缺少阻断明细；请核查证据。")
        else:
            lines.append("- 无未满足的硬阻断条件。")
        advisories = card.get("advisory_details", [])
        if advisories:
            lines.append("- 提示/需继续观察：")
            for item in advisories:
                relation = item.get("temporal_relation")
                if relation:
                    suffix = f"（{'移锚前' if relation == 'before' else '移锚后'}）"
                elif item.get("category") == "equipment":
                    suffix = "（时间关系未澄清）"
                elif item.get("detail", {}).get("role") in {
                    "termination_condition",
                    "termination_condition_for_maintain_position",
                }:
                    suffix = "（维持现位的终止条件：许可确认后转入下一判定）"
                else:
                    suffix = ""
                refs = " ".join(unique_refs(item.get("evidence_refs", [])))
                label = item.get("label") or item.get("key")
                lines.append(f"  - {label}{suffix} {refs}")
        if card.get("completion"):
            comp = card["completion"]
            lines.append(f"- 完成/航迹证据：`{comp.get('record_id')}`；该记录不可改写。")
        refs = " ".join(card.get("provenance_refs", []))
        if refs:
            lines.append(f"- 追溯：{refs}")
        lines.append("")

    lines.append("## 二、谁报告了什么")
    lines.append("")
    for item in briefing.get("who_reported_what", []):
        modality = {"conditional": "条件句", "unconditional": "无条件", "status": "状态说明"}.get(
            item.get("modality"), item.get("modality")
        )
        lines.append(
            f"- {item['provenance_refs'][0] if item.get('provenance_refs') else ''} "
            f"**{item.get('who')}**（记录渠道：{item.get('reporter')}）"
            f"[{modality}] {item.get('what')}"
        )
        for provenance in item.get("provenance", [])[:1]:
            quote = (provenance.get("quote") or "").replace("\n", " ")
            lines.append(f"  - 原句：“{quote}”")
    lines.append("")

    lines.append("## 三、海况/天气及适用条件")
    lines.append("")
    sea_conditions = briefing.get("sea_conditions") or briefing.get("next_watch", {}).get("sea_conditions", [])
    if sea_conditions:
        lines.append("### 行动卡引用的海况条件")
        for condition in sea_conditions:
            role = "建议性" if not condition.get("blocking", True) else "指令要求"
            refs = " ".join(condition.get("evidence_refs", []))
            lines.append(
                f"- `{condition.get('key')}` {condition.get('label')}："
                f"**{condition.get('state_zh')}**（{role}）{refs}"
            )
        lines.append("")
    lines.append("### 数值/定性观测")
    sea = briefing.get("sea_state", [])
    if not sea:
        lines.append("- 未提取到数值或定性海况记录。")
    for obs in sea:
        time_parts = []
        if obs.get("time_ref"):
            time_parts.append(f"时间表述：{obs.get('time_ref')}")
        time_window = (obs.get("attributes") or {}).get("time_window")
        if time_window:
            time_parts.append(f"适用时段：{time_window}")
        time_text = f"；{'，'.join(time_parts)}" if time_parts else ""
        refs = " ".join(unique_refs([evidence_ref(e) for e in obs.get("evidence", [])]))
        lines.append(f"- {obs.get('label')}（状态 `{obs.get('state')}`{time_text}）{refs}")
    lines.append("")

    lines.append("## 四、设备状态及时序")
    lines.append("")
    equipment = briefing.get("equipment_status", [])
    if not equipment:
        lines.append("- 未提取到设备状态。")
    for obs in equipment:
        relation = {"before": "发生在移锚前", "after": "发生在移锚后"}.get(
            obs.get("temporal_relation"), "与移锚的时间先后未澄清"
        )
        clarification = "；新日志已澄清" if obs.get("clarification") else ""
        value = f"；细节：{obs.get('value')}" if obs.get("value") else ""
        refs = " ".join(unique_refs([evidence_ref(e) for e in obs.get("evidence", [])]))
        lines.append(f"- {obs.get('label')}：`{obs.get('state')}`；{relation}{clarification}{value} {refs}")
    lines.append("")

    nw = briefing.get("next_watch", {})
    lines.append("## 五、传给下一班的确认条件")
    lines.append("")
    lines.append("### 已确认/已满足，可继续引用")
    confirmed = nw.get("confirmed_conditions", [])
    if not confirmed:
        lines.append("- 暂无已满足的关键条件。")
    for condition in confirmed:
        refs = " ".join(condition.get("evidence_refs", []))
        lines.append(f"- `{condition.get('key')}` {condition.get('label')} {refs}")
    lines.append("")
    lines.append("### 未满足，继续阻止行动")
    unresolved = nw.get("unresolved_blocking_conditions", [])
    if not unresolved:
        lines.append("- 无全局未满足硬条件；仍需核对各行动卡。")
    for condition in unresolved:
        refs = " ".join(condition.get("evidence_refs", []))
        lines.append(
            f"- `{condition.get('key')}` {condition.get('label')}：**{condition.get('state_zh')}** {refs}"
        )
    lines.append("")
    lines.append("### 下一班动作")
    for item in nw.get("continue_instructions", []):
        lines.append(f"- 继续：{item.get('title')} (`{item.get('card_id')}`)")
    for item in nw.get("do_not_start_until_unblocked", []):
        blocker_labels = "、".join(b.get("label", b.get("key")) for b in item.get("blockers", []))
        lines.append(f"- 不得启动：{item.get('title')} (`{item.get('card_id')}`)；待解除：{blocker_labels}")
    for item in nw.get("ready_for_command_decision", []):
        lines.append(f"- 可提交值班指挥决策：{item.get('title')} (`{item.get('card_id')}`)")
    for item in nw.get("completed_do_not_rewrite", []):
        lines.append(f"- 已完成归档，不得改写：{item.get('title')} (`{item.get('card_id')}`)")
    lines.append("")

    issues = briefing.get("issues", [])
    lines.append("## 六、冲突、歧义和审计提示")
    lines.append("")
    if not issues:
        lines.append("- 无。")
    for issue in issues:
        refs = " ".join(unique_refs([evidence_ref(e) for e in issue.get("evidence", [])]))
        severity = SEVERITY_ZH.get(issue.get("severity"), issue.get("severity"))
        lines.append(f"- **{severity}** `{issue.get('code')}`：{issue.get('message')} {refs}")
    lines.append("")
    lines.append("## 七、追溯方式")
    lines.append("")
    lines.append("- 每条主张、条件、观察和行动卡均带 `record_id`、`sentence_id` 与原句引文/字符范围。")
    lines.append("- 调用 `store.trace('<record-id>#S1')` 可反查引用该句的全部判断。")
    lines.append("- 新日志应使用新的记录编号；来源记录和哈希链航迹记录均不可覆盖。")
    lines.append("")
    return "\n".join(lines)
