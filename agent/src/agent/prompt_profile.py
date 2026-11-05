"""Conservative task routing projection. Never removes safety/grounding rules."""

import re

_FOREX = re.compile(r"\b(?:forex|mt5|exness|xauusdm|xagusdm)\b", re.I)
_OTHER_WORK = re.compile(r"\b(?:backtest|swarm|team|committee|factor|options?|pdf|csv|excel|shadow|journal|portfolio|document|code|python|mql5|ea)\b|kiểm định|mô phỏng|tối ưu|nhóm|đa tác tử|lập trình", re.I)


def project_prompt(template, user_message):
    if not _FOREX.search(user_message) or _OTHER_WORK.search(user_message):
        return template, "general"
    start, end = template.find("## Task Routing"), template.find("## Guidelines")
    if start < 0 or end <= start:
        return template, "general"
    routing = """## Task Routing
Native Forex research: use the native MT5 and historical-follow-up guidance below.
Do not launch a swarm/team unless the user explicitly requests one.
Other workflows remain available in the tool/skill catalogs. If the task changes,
load the relevant skill before doing backtests, strategy extraction or document work.

"""
    return template[:start] + routing + template[end:], "native_forex_research"
