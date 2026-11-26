"""Multilingual lexicon and small rule catalogues.

The rules cover the deliberately limited, fictional vocabulary used in the
exercise data.  They are deterministic and offline; no external NLP model is
required.
"""

from __future__ import annotations

import re

ROLE_LABELS_ZH = {
    "captain": "船长",
    "shore_station": "岸站",
    "equipment_officer": "设备员",
    "duty_officer": "值班驾驶员",
    "radio_operator": "无线电/值班报务",
    "translator": "翻译/转译岗",
    "track_system": "航迹系统",
    "unknown": "未知报告人",
}

KIND_ROLE = {
    "captain-note": "captain",
    "captain_order": "captain",
    "captain-log": "captain",
    "equipment-note": "equipment_officer",
    "equipment_log": "equipment_officer",
    "equipment-report": "equipment_officer",
    "radio-summary": "radio_operator",
    "radio-excerpt": "radio_operator",
    "radio-log": "radio_operator",
    "radio": "radio_operator",
    "bridge-log": "duty_officer",
    "watch-handover": "duty_officer",
    "shore-message": "shore_station",
    "shore-notice": "shore_station",
    "translation": "translator",
    "translated-summary": "translator",
    "track": "track_system",
    "track-point": "track_system",
}

SPEAKER_PATTERNS = [
    ("captain", re.compile(r"船长|船長|CAPT(?:\.|AIN)?\b|MASTER\b|OLD\s+MAN", re.I)),
    ("shore_station", re.compile(r"岸站|岸基|港调|港口调度|VTS\b|PORT\s+CONTROL|SHORE\s+(?:STATION|CONTROL)?|\bSHR\b|STATION\b", re.I)),
    ("equipment_officer", re.compile(r"设备员|設備員|电子员|電子員|ETO\b|EQUIPMENT\s+OFFICER|ELECTRICAL\s+OFFICER", re.I)),
    ("duty_officer", re.compile(r"值班驾驶员|值班駕駛員|值班人员|值班人員|驾驶员|駕駛員|OOW\b|DUTY\s+OFFICER|WATCH\s+OFFICER|MATE\b", re.I)),
    ("radio_operator", re.compile(r"报务员|報務員|无线电员|無線電員|R/?O\b|RADIO\s+OPERATOR", re.I)),
    ("translator", re.compile(r"翻译|翻譯|译文|譯文|TRANSLAT(?:ION|ED|OR)", re.I)),
]

# Order matters: more specific actions must precede generic vessel movement.
ACTION_PATTERNS: list[tuple[str, str, list[re.Pattern[str]]]] = [
    (
        "shift_anchor",
        "移锚 / shift anchor",
        [
            re.compile(p, re.I)
            for p in [
                r"移锚|移錨|移动锚位|移動錨位|起锚移位|起錨移位",
                r"\b(?:shift|move|relocate)\s+(?:the\s+)?(?:anchor|anchorage|anchor\s+position)\b",
                r"\banchor\s+(?:move|shift|movement|relocation)\b",
                r"\b(?:MOV|SHIFT|REL)\s+ANC(?:H?(?:OR)?)?\b",
                r"\bANC(?:H?(?:OR)?)?\s+(?:MOV|SHIFT|REL)\b",
            ]
        ],
    ),
    (
        "maintain_position",
        "维持现位 / maintain position",
        [
            re.compile(p, re.I)
            for p in [
                r"维持现位|維持現位|保持(?:现|現)?位|守候(?:原位)?|原地待命|不要移锚|勿移锚",
                r"\b(?:maintain|hold|keep)\s+(?:(?:the|current|present)\s+)?(?:position|posn|pos)\b",
                r"\bSTAY\s+(?:AT\s+)?(?:POSITION|POSN|POS)\b",
                r"\bRMN\s+POS(?:N)?\b",
            ]
        ],
    ),
    (
        "start_operations",
        "开始作业 / start operations",
        [
            re.compile(p, re.I)
            for p in [
                r"开始作业|開始作業|启动作业|啟動作業|开展作业|開展作業|开始调查|開始調查",
                r"\b(?:start|commence|begin)\s+(?:survey\s+)?operations?\b",
                r"\bSTART\s+OPS?\b|\bCOMM(?:ENCE)?\s+OPS?\b",
            ]
        ],
    ),
]

GENERIC_MOVEMENT_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"移船|移动|移動",
        r"\b(?:moving|move|shift(?:ing)?|relocat\w*|under\s+way)\b",
    ]
]

CONDITION_PATTERNS: list[tuple[str, str, str, list[re.Pattern[str]]]] = [
    (
        "weather.wind_east",
        "风转东 / wind turns east",
        "weather",
        [
            re.compile(p, re.I)
            for p in [
                r"风(?:已|已经)?转东|風(?:已|已經)?轉東|风向转东|風向轉東|转东风|轉東風|东风",
                r"\bwind\s+(?:turns?|shifts?|veers?)\s+(?:to\s+)?(?:the\s+)?east(?:erly)?\b",
                r"\beast(?:erly)?\s+wind\b|\bwind\s+E(?:AST)?\b",
                r"\bWND\s+E\b",
            ]
        ],
    ),
    (
        "weather.gust_passed",
        "当前阵风过去 / current gust passes",
        "weather",
        [
            re.compile(p, re.I)
            for p in [
                r"阵风(?:过去|過去|结束|結束|减弱|減弱)|大风间歇",
                r"\b(?:current\s+)?gust\s+(?:passes?|has\s+passed|over|ends?|subsides?)\b",
                r"\bafter\s+the\s+current\s+gust\b",
                r"\bGUST\s+(?:OVER|PASS(?:ED)?|END)\b",
            ]
        ],
    ),
    (
        "authorization.shore_clearance",
        "岸站确认/移锚许可 / shore confirmation or clearance",
        "authorization",
        [
            re.compile(p, re.I)
            for p in [
                r"岸站(?:已(?:经)?)?(?:确认|確認|批准|许可|許可|签发|簽發|同意)|"
                r"岸基(?:已(?:经)?)?(?:确认|確認|批准|许可|許可|签发|簽發|同意)|"
                r"收到.{0,8}(?:确认|確認|批准|许可|許可)|"
                r"(?:已(?:经)?)?(?:批准|许可|許可|同意)移锚",
                r"\bshore\s+(?:confirmation|clearance|approval|permission)\b",
                r"\bclearance\b|\bapproval\b|\bpermission\s+(?:granted|received)?\b",
                r"\bCLR(?:ANCE)?\b|\bCONF(?:IRM(?:ATION|ED)?)?\b",
            ]
        ],
    ),
    (
        "equipment.positioning_normal",
        "定位信号恢复正常 / stable positioning",
        "equipment",
        [
            re.compile(p, re.I)
            for p in [
                r"定位(?:信号|訊號|系统|系統)?(?:恢复|恢復|正常|稳定|穩定)",
                r"(?:GPS|GNSS|DGPS|positioning?|position\s+signal|POSN?)\s+(?:restored|back\s+to\s+normal|normal|stable|recovered)",
                r"\bPOSN?\s+OK\b|\bGPS\s+OK\b",
            ]
        ],
    ),
]

CONDITIONAL_MARKER = re.compile(
    r"等|待|等到|待至|在?.{0,8}(?:以后|之後|之后)|之前|以前|"
    r"(?<![当目])前|后再|後再|后才|後才|后就|後就|后[，,。；;]|後[，,。；;]|"
    r"只有|除非|若|如果|假如|一经|一經|"
    r"after|once|when|as soon as|before|until|till|subject to|provided that|only after|only when",
    re.I,
)

POSITIVE_AUTHORIZATION = re.compile(
    r"已(?:收到|获得|獲得|批准|许可|許可|确认|確認|签发|簽發)|"
    r"(?:clearance|approval|permission|confirmation)[^.;。\n]{0,25}?"
    r"(?:has\s+been\s+)?(?:issued|granted|approved|received)|"
    r"(?:issued|granted|approved|received)[^.;。\n]{0,25}?"
    r"(?:clearance|approval|permission|confirmation)|"
    r"shore\s+(?:has\s+)?approved|\bAPPROVED\b|\bCLEARED\b|\bCLR\s+(?:RCVD|ISSUED|GRANTED)\b",
    re.I,
)

NEGATIVE_AUTHORIZATION = re.compile(
    r"未收到|尚未(?:收到|获得|獲得|批准|许可|許可|确认|確認|签发|簽發)?|没有(?:收到|批准|许可|許可|确认|確認|签发|簽發)?|并无(?:许可|許可)?|"
    r"no\s+(?:shore\s+)?(?:clearance|approval|permission|confirmation)\s+(?:has\s+been\s+)?(?:issued|granted|received)?|"
    r"clearance\s+(?:has\s+not\s+been|not)\s+(?:issued|granted|received)?|"
    r"not\s+(?:yet\s+)?(?:approved|cleared|confirmed|authorized|authorised)|"
    r"approval\s+pending|clearance\s+pending|"
    r"\bNO\s+CLR\b|\bNIL\s+CLR\b|\bCLR\s+NIL\b|\bNOT\s+CONF(?:IRMED)?\b|\bUNCONFIRMED\b",
    re.I,
)

COMPLETION_MARKER = re.compile(
    r"已(?:经|經)?(?:转|轉|变|變|过|過|完成|结束|結束|签发|簽發|批准|确认|確認|恢复|恢復)|已于|已於|"
    r"\bhas\s+(?:already\s+)?(?:turned|shifted|passed|been\s+issued|been\s+granted|completed|finished|restored)\b|"
    r"\b(?:turned|shifted)\s+east\b|\bnow\s+(?:east|normal|stable)\b|\bcompleted\b|\bfinished\b|\bdone\b",
    re.I,
)

SUGGESTION_PATTERN = re.compile(
    r"建议|建議|提议|提議|可(?:以)?|不妨|"
    r"\bsuggest(?:s|ed|ion)?\b|\brecommend(?:s|ed|ation)?\b|\badvise[sd]?\b|\bmaybe\b|\bcould\b",
    re.I,
)

ORDER_PATTERN = re.compile(
    r"命令|指示|要求|务必|務必|必须|必須|不得|不准|"
    r"\border(?:s|ed)?\b|\bdirect(?:s|ed|ion)?\b|\bmust\b|\bshall\b|\brequire[sd]?\b|\bdo\s+not\b|\bdon'?t\b|\bhold\b",
    re.I,
)

TRANSLATION_MARKER = re.compile(
    r"译文|譯文|翻译|翻譯|转译|轉譯|英译中|中译英|"
    r"\btranslation\b|\btranslated\b|\bas\s+translated\b|\bEN[- ]?ZH\b|\bZH[- ]?EN\b",
    re.I,
)

APPROVED_UNCONDITIONAL_PATTERN = re.compile(
    r"(?:岸站|shore)?[^\n。；;]{0,20}(?:已批准|批准移锚|许可移锚|許可移錨|同意移锚)|"
    r"\b(?:shore\s+)?(?:approved|cleared|authori[sz]ed)\s+(?:the\s+)?anchor\s+move\b|"
    r"\banchor\s+move\s+(?:is\s+)?approved\b",
    re.I,
)

EQUIPMENT_SUBJECT = re.compile(
    r"定位(?:信号|訊號|系统|系統|数据|數據)?|GPS|GNSS|DGPS|"
    r"position(?:ing)?(?:\s+signal|\s+system)?|\bPOSN?\b|"
    r"设备故障|設備故障|装备故障|裝備故障|"
    r"equipment\s+(?:fault|failure|malfunction|outage)|\bfault\b|\boutage\b",
    re.I,
)

EQUIPMENT_INTERMITTENT = re.compile(
    r"每隔几分钟丢(?:一)?次|每隔[0-9０-９]+(?:分钟|分鐘|min|m)[^，。；]{0,8}(?:丢|掉|lost|drop)|"
    r"间歇|間歇|时断时续|時斷時續|断断续续|斷斷續續|偶尔丢失|偶爾丟失|不稳定|不穩定|"
    r"\bintermittent(?:ly)?\b|\bdrops?\s+(?:out\s+)?(?:every\s+few\s+minutes|periodically|now\s+and\s+then)\b|"
    r"(?:position(?:ing)?|GPS|GNSS|POSN?)[^.;，,。]{0,18}\bdrops?\b|"
    r"\bkeeps?\s+dropping\b|\bflaky\b|\bINT(?:ERMIT)?\b",
    re.I,
)

EQUIPMENT_LOST = re.compile(
    r"信号丢失|訊號丟失|完全丢失|完全丟失|失灵|失靈|失效|中断|中斷|无信号|無訊號|無信号|"
    r"\blost\s+(?:positioning|GPS|GNSS|DGPS|signal)\b|\b(?:GPS|GNSS|signal)\s+(?:lost|down|out|offline|unavailable)\b|"
    r"\boutage\b|\bno\s+(?:position|GPS|GNSS|DGPS)?\s*signal\b|\bPOSN?\s+(?:LOST|OUT|U/S)\b",
    re.I,
)

EQUIPMENT_NORMAL = re.compile(
    r"恢复正常|恢復正常|已恢复|已恢復|正常|稳定|穩定|"
    r"\brestored\b|\bback\s+to\s+normal\b|\bnormal\b|\bstable\b|\bOK\b",
    re.I,
)

TIME_UNKNOWN = re.compile(
    r"时间未记录|時間未記錄|时间不详|時間不詳|未记录时间|未記錄時間|"
    r"\btime\s+(?:not\s+recorded|unknown|unrecorded)\b|\btiming\s+unknown\b|\bno\s+timestamp\b",
    re.I,
)

CLARIFICATION = re.compile(
    r"澄清|查明|核实|核實|确认时间|確認時間|时间确定|時間確定|更正|补充记录|補充記錄|"
    r"\bclarif(?:y|ied|ication)\b|\bconfirmed\s+(?:the\s+)?timing\b|\bactually\b|\bcorrect(?:ed|ion)?\b|\bupdate[sd]?\b",
    re.I,
)

TEMPORAL_BEFORE_ANCHOR = re.compile(
    r"(?:发生|發生|出现|出現)?在?\s*移锚\s*(?:之)?前|锚移(?:之)?前|"
    r"\bbefore\s+(?:the\s+)?(?:anchor\s+move|moving\s+(?:the\s+)?anchor|anchor\s+shift|shift(?:ing)?\s+anchor)\b",
    re.I,
)

TEMPORAL_AFTER_ANCHOR = re.compile(
    r"(?:发生|發生|出现|出現)?在?\s*移锚\s*(?:之)?后|移锚\s*(?:之)?後|锚移(?:之)?后|"
    r"\bafter\s+(?:the\s+)?(?:anchor\s+move|moving\s+(?:the\s+)?anchor|anchor\s+shift|shift(?:ing)?\s+anchor)\b",
    re.I,
)

TIME_REF = re.compile(
    r"\d{4}-\d{2}-\d{2}[T\s]\d{1,2}:\d{2}(?::\d{2})?|\d{1,2}:\d{2}(?::\d{2})?|"
    r"\d{1,2}\s*时(?:\d{1,2}\s*分)?|\d{1,2}\s*時(?:\d{1,2}\s*分)?|"
    r"(?:当前|目前|刚才|剛才|预计|預計|今晚|明早|下午|上午)|"
    r"\b(?:now|currently|at\s+\d{1,2}:\d{2}|before|after)\b",
    re.I,
)

TIME_WINDOW = re.compile(
    r"\d{1,2}:\d{2}\s*(?:-|–|—|~|至|到)\s*\d{1,2}:\d{2}|"
    r"\d{1,2}\s*时(?:\d{1,2}\s*分)?\s*(?:-|–|—|~|至|到)\s*\d{1,2}\s*时(?:\d{1,2}\s*分)?|"
    r"\b\d{1,2}:\d{2}\s*(?:-|–|—|to|until)\s*\d{1,2}:\d{2}\b",
    re.I,
)

SEA_NUMERIC = re.compile(
    r"(?P<subject>浪高|有效波高|浪|涌高|湧高|能见度|能見度|风力|風力|风速|風速|海况|海況|"
    r"wave\s+height|significant\s+wave\s+height|seas?|swell|visibility|wind\s+speed|wind\s+force|sea\s+state)"
    r"[^0-9A-Za-z一-鿿]{0,18}?"
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>米|m|metres?|meters?|级|級|bf|beaufort|节|節|knots?|kt|km/?h|公里)?",
    re.I,
)

SEA_QUALITATIVE = re.compile(
    r"轻浪|輕浪|中浪|大浪|巨浪|小浪|平静|海况(?:良好|恶劣|惡劣)?|"
    r"\b(?:calm|smooth|slight|moderate|rough|very\s+rough|high)\s+seas?\b",
    re.I,
)

TRACK_KIND = {"track", "track-point", "track_point", "position-record", "completed-track"}
COMPLETION_KIND = {"completion", "action-completion", "outcome"}
