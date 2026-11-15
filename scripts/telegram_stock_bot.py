"""Manage the STOCK_LIST repository variable from Telegram.

Runs on a schedule in GitHub Actions. It reads pending messages for the bot
(getUpdates), answers only the chat in TELEGRAM_CHAT_ID, applies commands to
the STOCK_LIST Actions variable, and confirms the processed updates.

Commands (Korean aliases in brackets):
  /list            [목록]        show the current list
  /add A B ...     [추가 A B]    add codes
  /remove A B ...  [삭제 A B]    remove codes
  /set A,B,C       [설정 A,B,C]  replace the whole list
  /help            [도움말]
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = str(os.environ["TELEGRAM_CHAT_ID"]).strip()
GH_TOKEN = os.environ.get("GH_VARIABLES_TOKEN", "").strip()
REPO = os.environ["GITHUB_REPOSITORY"]
VAR_NAME = "STOCK_LIST"
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-^=]{0,19}$")

HELP = (
    "📋 종목 관리 명령어\n"
    "/list (목록) - 현재 종목 보기\n"
    "/add 코드 ... (추가) - 종목 추가\n"
    "/remove 코드 ... (삭제) - 종목 삭제\n"
    "/set 코드,코드 (설정) - 목록 전체 바꾸기\n\n"
    "예) /add NVDA 005930.KS\n"
    "코스피 .KS / 코스닥 .KQ / 미국은 티커 그대로\n"
    "바뀐 목록은 다음 정기 분석부터 적용돼요."
)
ALIASES = {"목록": "/list", "추가": "/add", "삭제": "/remove", "설정": "/set", "도움말": "/help"}


def _request(url, method="GET", data=None, headers=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def tg(method, **params):
    return _request(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", "POST", params)


def gh(path, method="GET", data=None):
    return _request(
        f"https://api.github.com/repos/{REPO}{path}",
        method,
        data,
        {
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "telegram-stock-bot",
        },
    )


def load_list():
    try:
        value = gh(f"/actions/variables/{VAR_NAME}").get("value", "")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        value = ""
    return [c.strip() for c in value.split(",") if c.strip()]


def save_list(codes):
    value = ",".join(codes)
    try:
        gh(f"/actions/variables/{VAR_NAME}", "PATCH", {"name": VAR_NAME, "value": value})
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        gh("/actions/variables", "POST", {"name": VAR_NAME, "value": value})


def parse_codes(args):
    codes, bad = [], []
    for token in re.split(r"[\s,]+", args.strip()):
        if not token:
            continue
        if CODE_RE.match(token):
            code = token if token.lower().startswith(("hk", "sh", "sz")) else token.upper()
            if code not in codes:
                codes.append(code)
        else:
            bad.append(token)
    return codes, bad


def fmt(codes):
    return "\n".join(f"• {c}" for c in codes) if codes else "(비어 있음)"


def handle(text, codes):
    """Return (reply, new_codes or None if unchanged)."""
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].split("@")[0]
    cmd = ALIASES.get(cmd, cmd).lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd in ("/list", "/start"):
        return f"📈 현재 종목 ({len(codes)}개)\n{fmt(codes)}", None
    if cmd == "/help":
        return HELP, None
    if cmd in ("/add", "/remove", "/set"):
        new, bad = parse_codes(args)
        note = f"\n⚠️ 형식이 이상해서 뺀 값: {', '.join(bad)}" if bad else ""
        if not new:
            return f"종목 코드를 같이 적어 주세요. 예) {cmd} NVDA{note}", None
        if cmd == "/add":
            added = [c for c in new if c not in codes]
            result = codes + added
            head = f"✅ 추가: {', '.join(added)}" if added else "이미 있는 종목이에요."
        elif cmd == "/remove":
            lowered = {c.lower() for c in new}
            removed = [c for c in codes if c.lower() in lowered]
            result = [c for c in codes if c.lower() not in lowered]
            head = f"🗑 삭제: {', '.join(removed)}" if removed else "목록에 없는 종목이에요."
        else:
            result = new
            head = "🔄 목록을 바꿨어요."
        if not result:
            return "목록을 비울 수는 없어요. 최소 1개는 남겨 주세요.", None
        changed = result != codes
        return f"{head}{note}\n\n📈 현재 종목 ({len(result)}개)\n{fmt(result)}", (result if changed else None)
    return None, None  # ignore ordinary chat


def main():
    if not GH_TOKEN:
        print("GH_VARIABLES_TOKEN secret is not set; skipping (messages stay queued).")
        return
    updates = tg("getUpdates", timeout=0, allowed_updates=["message"]).get("result", [])
    if not updates:
        print("no updates")
        return
    codes = load_list()
    for upd in updates:
        msg = upd.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        text = msg.get("text") or ""
        if chat_id != CHAT_ID:
            print(f"ignored update {upd['update_id']} from another chat")
            continue
        if not text.strip():
            continue
        reply, new_codes = handle(text, codes)
        if new_codes is not None:
            save_list(new_codes)
            codes = new_codes
        if reply:
            tg("sendMessage", chat_id=CHAT_ID, text=reply)
        print(f"handled update {upd['update_id']}")
    # Confirm everything we have seen so it is not delivered again.
    tg("getUpdates", offset=updates[-1]["update_id"] + 1, timeout=0)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read()[:300]!r}", file=sys.stderr)
        sys.exit(1)
