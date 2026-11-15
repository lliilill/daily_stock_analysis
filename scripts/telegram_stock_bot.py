"""Manage the STOCK_LIST repository variable from Telegram, with buttons.

Runs from a scheduled GitHub Actions job. Each run long-polls the bot for a
few minutes, answers only the chat in TELEGRAM_CHAT_ID, and writes changes to
the STOCK_LIST Actions variable.

Buttons under the chat box: 📋 목록 / ➕ 추가 / ➖ 삭제 / ❓ 도움말
  ➕ 추가 asks for codes (reply with e.g. "NVDA 005930.KS")
  ➖ 삭제 shows one button per stock; tap to remove it
Text commands still work: /list /add /remove /set /help (목록 추가 삭제 설정 도움말)
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = str(os.environ["TELEGRAM_CHAT_ID"]).strip()
GH_TOKEN = os.environ.get("GH_VARIABLES_TOKEN", "").strip()
REPO = os.environ["GITHUB_REPOSITORY"]
RUN_SECONDS = int(os.environ.get("BOT_RUN_SECONDS", "0") or 0)
VAR_NAME = "STOCK_LIST"
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-^=]{0,19}$")

BTN_LIST, BTN_ADD, BTN_DEL, BTN_HELP = "📋 목록", "➕ 추가", "➖ 삭제", "❓ 도움말"
ADD_PROMPT = "➕ 추가할 종목 코드를 이 메시지에 답장으로 보내 주세요."
MAIN_KEYBOARD = {
    "keyboard": [[BTN_LIST, BTN_ADD], [BTN_DEL, BTN_HELP]],
    "resize_keyboard": True,
    "is_persistent": True,
}
HELP = (
    "📋 종목 관리\n"
    f"{BTN_LIST} - 현재 종목 보기\n"
    f"{BTN_ADD} - 코드를 답장으로 보내면 추가\n"
    f"{BTN_DEL} - 종목 버튼을 눌러 삭제\n\n"
    "코드 예) NVDA, 005930.KS(코스피), 247540.KQ(코스닥)\n"
    "글자로도 돼요: 추가 NVDA / 삭제 JEPI / 설정 AAPL,MSFT\n"
    "바뀐 목록은 다음 정기 분석부터 적용돼요.\n"
    "버튼 응답은 GitHub 실행 간격 때문에 몇 분 늦을 수 있어요."
)
ALIASES = {
    "목록": "/list", "추가": "/add", "삭제": "/remove", "설정": "/set", "도움말": "/help",
    BTN_LIST: "/list", BTN_ADD: "/add", BTN_DEL: "/remove", BTN_HELP: "/help",
}


# ---------------------------------------------------------------- HTTP helpers
def _request(url, method="GET", data=None, headers=None, timeout=30):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def tg(method, timeout=30, **params):
    return _request(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", "POST", params, timeout=timeout)


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


# ---------------------------------------------------------------- pure logic
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


def summary(codes):
    return f"📈 현재 종목 ({len(codes)}개)\n{fmt(codes)}"


def delete_keyboard(codes):
    rows, row = [], []
    for c in codes:
        row.append({"text": f"❌ {c}", "callback_data": f"del:{c}"[:64]})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


def apply_change(cmd, new, codes):
    """Return (head_text, result_codes) for /add, /remove, /set."""
    if cmd == "/add":
        added = [c for c in new if c not in codes]
        return (f"✅ 추가: {', '.join(added)}" if added else "이미 있는 종목이에요."), codes + added
    if cmd == "/remove":
        lowered = {c.lower() for c in new}
        removed = [c for c in codes if c.lower() in lowered]
        result = [c for c in codes if c.lower() not in lowered]
        return (f"🗑 삭제: {', '.join(removed)}" if removed else "목록에 없는 종목이에요."), result
    return "🔄 목록을 바꿨어요.", new


def handle_text(text, codes, replying_to=""):
    """Return (reply_text, reply_markup, new_codes or None)."""
    text = text.strip()
    if replying_to.startswith(ADD_PROMPT[:10]):
        text = f"/add {text}"
    parts = text.split(maxsplit=1)
    cmd = parts[0].split("@")[0]
    cmd = ALIASES.get(text, ALIASES.get(cmd, cmd)).lower()
    args = parts[1] if len(parts) > 1 and text not in ALIASES else ""

    if cmd in ("/list", "/start"):
        return summary(codes), MAIN_KEYBOARD, None
    if cmd == "/help":
        return HELP, MAIN_KEYBOARD, None
    if cmd == "/add" and not args:
        return ADD_PROMPT, {"force_reply": True, "input_field_placeholder": "예: NVDA 005930.KS"}, None
    if cmd == "/remove" and not args:
        if not codes:
            return "삭제할 종목이 없어요.", MAIN_KEYBOARD, None
        return "➖ 삭제할 종목을 누르세요.", delete_keyboard(codes), None
    if cmd in ("/add", "/remove", "/set"):
        new, bad = parse_codes(args)
        note = f"\n⚠️ 형식이 이상해서 뺀 값: {', '.join(bad)}" if bad else ""
        if not new:
            return f"종목 코드를 알아보지 못했어요.{note}", MAIN_KEYBOARD, None
        head, result = apply_change(cmd, new, codes)
        if not result:
            return "목록을 비울 수는 없어요. 최소 1개는 남겨 주세요.", MAIN_KEYBOARD, None
        changed = result != codes
        return f"{head}{note}\n\n{summary(result)}", MAIN_KEYBOARD, (result if changed else None)
    return None, None, None  # ignore ordinary chat


def handle_callback(data, codes):
    """Return (reply_text, new_codes or None) for an inline button tap."""
    if not data.startswith("del:"):
        return None, None
    code = data[4:]
    head, result = apply_change("/remove", [code], codes)
    if not result:
        return "목록을 비울 수는 없어요. 최소 1개는 남겨 주세요.", None
    return f"{head}\n\n{summary(result)}", (result if result != codes else None)


# ---------------------------------------------------------------- loop
def process(updates, codes):
    for upd in updates:
        if "callback_query" in upd:
            cq = upd["callback_query"]
            msg = cq.get("message") or {}
            if str((msg.get("chat") or {}).get("id", "")) != CHAT_ID:
                continue
            reply, new_codes = handle_callback(cq.get("data") or "", codes)
            try:
                tg("answerCallbackQuery", callback_query_id=cq["id"])
            except urllib.error.HTTPError:
                pass  # too old to answer; the change still applies
            if new_codes is not None:
                save_list(new_codes)
                codes = new_codes
            if reply:
                tg("sendMessage", chat_id=CHAT_ID, text=reply, reply_markup=MAIN_KEYBOARD)
            print(f"handled callback {upd['update_id']}")
            continue

        msg = upd.get("message") or {}
        if str((msg.get("chat") or {}).get("id", "")) != CHAT_ID:
            print(f"ignored update {upd['update_id']} from another chat")
            continue
        text = msg.get("text") or ""
        if not text.strip():
            continue
        replying_to = ((msg.get("reply_to_message") or {}).get("text")) or ""
        reply, markup, new_codes = handle_text(text, codes, replying_to)
        if new_codes is not None:
            save_list(new_codes)
            codes = new_codes
        if reply:
            tg("sendMessage", chat_id=CHAT_ID, text=reply, reply_markup=markup)
        print(f"handled update {upd['update_id']}")
    return codes


def main():
    if not GH_TOKEN:
        print("GH_VARIABLES_TOKEN secret is not set; skipping (messages stay queued).")
        return
    deadline = time.time() + RUN_SECONDS
    offset = None
    codes = None
    while True:
        remaining = int(deadline - time.time())
        wait = max(0, min(50, remaining))
        params = {"timeout": wait, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        updates = tg("getUpdates", timeout=wait + 15, **params).get("result", [])
        if updates:
            if codes is None:
                codes = load_list()
            codes = process(updates, codes)
            offset = updates[-1]["update_id"] + 1
        if time.time() >= deadline:
            break
    if offset is not None:
        tg("getUpdates", offset=offset, timeout=0)  # confirm processed updates


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read()[:300]!r}", file=sys.stderr)
        sys.exit(1)
