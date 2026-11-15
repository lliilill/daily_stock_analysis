"""Translate the English report scaffolding left in Korean reports.

Korean reports reuse the English market-review templates (headings, the
market-signal block, the index table header). This rewrites those fixed
phrases just before a report is sent or saved. Model-written prose is left
alone; only known template strings are replaced.
"""

import re

_HEADINGS = {
    "A-share Market Recap": "A주 증시 리뷰",
    "US Market Recap": "미국 증시 리뷰",
    "HK Market Recap": "홍콩 증시 리뷰",
    "Japan Market Recap": "일본 증시 리뷰",
    "Korea Market Recap": "한국 증시 리뷰",
    "Taiwan Market Recap": "대만 증시 리뷰",
    "Market Recap": "증시 리뷰",
    "Market Summary": "시장 요약",
    "Index Commentary": "지수 코멘트",
    "Major Indices": "주요 지수",
    "Fund Flows": "자금 흐름",
    "Sector/Theme Highlights": "섹터·테마 동향",
    "Sector Highlights": "섹터 동향",
    "News Catalysts": "뉴스 촉매",
    "Outlook": "전망",
    "Risk Alerts": "리스크 경고",
    "Strategy Plan": "전략",
    "Strategy Framework": "전략 프레임워크",
    "Leading Industry Sectors": "강세 업종",
    "Lagging Industry Sectors": "약세 업종",
    "Leading Sectors": "강세 섹터",
    "Lagging Sectors": "약세 섹터",
}

_PHRASES = [
    ("**Market Signal**", "**시장 신호**"),
    ("**Drivers**", "**근거**"),
    ("**Guidance**", "**가이드**"),
    ("**Breadth**", "**시장 폭**"),
    ("| Index | Last | Change % | Open | High | Low | Amplitude | Turnover (",
     "| 지수 | 현재가 | 등락률 | 시가 | 고가 | 저가 | 변동폭 | 거래대금 ("),
    ("| Rank | Sector | Change |", "| 순위 | 섹터 | 등락률 |"),
    ("Risk appetite is acceptable; focus on leading themes and position discipline.",
     "위험 선호가 양호해요. 주도 테마에 집중하되 비중 원칙을 지키세요."),
    ("Signals are mixed; keep position sizing moderate and wait for confirmation.",
     "신호가 엇갈려요. 비중을 적당히 유지하고 방향 확인을 기다리세요."),
    ("Risk is elevated; prioritize drawdown control and avoid chasing weak rebounds.",
     "위험이 높아요. 손실 관리를 우선하고 약한 반등 추격은 피하세요."),
    ("limited structured breadth data; using available market inputs",
     "시장 폭 데이터가 부족해 가용 데이터로 판단"),
    ("For reference only, not investment advice.", "참고용이며 투자 권유가 아닙니다."),
    ("USD bn", "십억 달러"),
    ("KRW bn", "십억 원"),
]

_LABELS = {
    "risk-on": "공격 가능",
    "constructive": "우호적",
    "mixed": "혼조",
    "defensive": "방어적",
    "balanced": "관망",
    "risk-off": "방어",
}

_REGEX = [
    (re.compile(r"average major-index change ([+-]?\d+(?:\.\d+)?%)"), r"주요 지수 평균 등락 \1"),
    (re.compile(r"advancers ratio (\d+%), breadth is expanding"), r"상승 종목 비율 \1, 시장 폭 확대"),
    (re.compile(r"advancers ratio (\d+%), downside pressure dominates"), r"상승 종목 비율 \1, 하락 압력 우세"),
    (re.compile(r"advancers ratio (\d+%), breadth is mixed"), r"상승 종목 비율 \1, 시장 폭 혼조"),
    (re.compile(r"limit-up/down spread ([+-]?\d+)"), r"상한가-하한가 차이 \1"),
]

_HEADING_LINE = re.compile(r"^(#{1,6}\s*(?:\d+\.\s*)?)(.*)$")
_SIGNAL_PAREN = re.compile(r"(\*\*시장 신호\*\*: \d+/100 \\?\()([a-z-]+), ([a-z-]+)(\\?\))")


def _translate_heading(text):
    for en, ko in sorted(_HEADINGS.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(en, ko)
    return text


def koreanize_report(content):
    if not content:
        return content
    lines = []
    for line in content.split("\n"):
        m = _HEADING_LINE.match(line)
        if m:
            line = m.group(1) + _translate_heading(m.group(2))
        lines.append(line)
    text = "\n".join(lines)
    for en, ko in _PHRASES:
        text = text.replace(en, ko)
    for pattern, repl in _REGEX:
        text = pattern.sub(repl, text)
    text = _SIGNAL_PAREN.sub(
        lambda m: f"{m.group(1)}{_LABELS.get(m.group(2), m.group(2))}, "
        f"{_LABELS.get(m.group(3), m.group(3))}{m.group(4)}",
        text,
    )
    return text
