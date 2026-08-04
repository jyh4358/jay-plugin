#!/usr/bin/env python3
"""jay-plugin statusline — Claude Code 상태줄 렌더러.

Claude Code가 statusline 명령의 stdin으로 넘겨주는 JSON만으로 렌더링한다
(네트워크 호출·외부 의존성 없음).

2행 구성이다. 1행은 길이가 변하는 정체성(모델·브랜치), 2행은 폭이 거의 고정인
수치(플랜 사용량·세션·컨텍스트). 좌우 분할된 좁은 pane에서 한 줄로 붙이면
'...'으로 잘려 뒷부분이 안 보이므로, 세그먼트 경계가 흔들리지 않는 고정 2행으로 나눈다.

  Model: Fable 5 | branch:feat-x (wt:feat-x)
    5h:[█░░░░░░░]4%(4h48m) wk:[█░░░░░░░]17%(5d15h) | session:3m | ctx:[█░░░░░░░░░]7%

stdin 필드 (Claude Code v2.x):
  model.display_name
  rate_limits.five_hour / seven_day  → used_percentage, resets_at(unix초 또는 ISO)
  context_window.used_percentage     → 없으면 current_usage로 계산
  cost.total_duration_ms             → 세션 경과 시간

rate_limits는 구독(OAuth) 사용자에게만 제공된다. 없으면 해당 구간을 생략한다.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime

GREEN = "\x1b[32m"
CYAN = "\x1b[36m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"

RATE_BAR_WIDTH = 8
CTX_BAR_WIDTH = 10
FILLED = "█"
EMPTY = "░"

WARNING_PCT = 70
CRITICAL_PCT = 90

# 세션 경과 시간 임계값(분). ctx% 와 무관하게 시간만으로 판정한다.
SESSION_WARNING_MIN = 60
SESSION_CRITICAL_MIN = 120

# 2행 들여쓰기. 1행(정체성)과 2행(수치)을 눈으로 구분하기 위한 것.
BODY_INDENT = "  "


def color_for(percent):
    if percent >= CRITICAL_PCT:
        return RED
    if percent >= WARNING_PCT:
        return YELLOW
    return GREEN


def clamp_pct(value):
    try:
        return min(100, max(0, round(float(value))))
    except (TypeError, ValueError):
        return None


def bar(percent, width):
    filled = round(percent / 100 * width)
    color = color_for(percent)
    return f"[{color}{FILLED * filled}{DIM}{EMPTY * (width - filled)}{RESET}]"


def format_reset(resets_at):
    """resets_at(unix초/밀리초 또는 ISO 문자열) → '4h48m' / '5d15h'. 과거·파싱 불가면 None."""
    if resets_at is None:
        return None
    try:
        if isinstance(resets_at, str):
            ts = datetime.fromisoformat(resets_at.replace("Z", "+00:00")).timestamp()
        else:
            ts = float(resets_at)
            if ts > 1e12:  # 밀리초
                ts /= 1000
    except (ValueError, OSError):
        return None

    diff = ts - time.time()
    if diff <= 0:
        return None
    minutes = int(diff // 60)
    hours, days = minutes // 60, minutes // (60 * 24)
    if days > 0:
        return f"{days}d{hours % 24}h"
    return f"{hours}h{minutes % 60}m"


def format_duration(minutes):
    """경과 분 → '7m' / '2h5m' / '5d3h'. 재개를 반복한 긴 세션도 한눈에 읽히게."""
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h{minutes % 60}m"
    return f"{hours // 24}d{hours % 24}h"


def session_color_for(minutes):
    """세션 색은 경과 시간만으로 결정한다.

    이전에는 ctx% 도 함께 봤는데, 그러면 경과 시간이 그대로인데도 컨텍스트가
    차오르는 것만으로 session 색이 바뀌어 무엇을 경고하는지 알 수 없었다.
    컨텍스트는 바로 옆 ctx 세그먼트가 이미 색으로 알려 준다.
    """
    if minutes >= SESSION_CRITICAL_MIN:
        return RED
    if minutes >= SESSION_WARNING_MIN:
        return YELLOW
    return GREEN


def render_rate_window(label, window, dim_label):
    if not isinstance(window, dict):
        return None
    pct = clamp_pct(window.get("used_percentage"))
    if pct is None:
        return None
    color = color_for(pct)
    prefix = f"{DIM}{label}:{RESET}" if dim_label else f"{label}:"
    part = f"{prefix}{bar(pct, RATE_BAR_WIDTH)}{color}{pct}%{RESET}"
    reset_str = format_reset(window.get("resets_at"))
    if reset_str:
        part += f"{DIM}({reset_str}){RESET}"
    return part


def git_segment(data):
    """현재 브랜치 + linked worktree 표시: 'branch:main' / 'branch:feat-x (wt:feat-x)'.

    git-dir와 git-common-dir가 다르면 linked worktree이며,
    워크트리 이름은 git-dir 경로의 마지막 요소(.git/worktrees/<이름>)다.
    """
    cwd = (data.get("workspace") or {}).get("current_dir") or data.get("cwd")
    if not cwd or not os.path.isdir(cwd):
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD", "--git-dir", "--git-common-dir"],
            cwd=cwd, capture_output=True, text=True, timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = proc.stdout.strip().splitlines()
    if proc.returncode != 0 or len(lines) < 3:
        return None

    branch, git_dir, common_dir = lines[0], lines[1], lines[2]
    if branch == "HEAD":
        branch = "detached"
    part = f"{DIM}branch:{RESET}{CYAN}{branch}{RESET}"

    def canon(p):
        return os.path.realpath(p if os.path.isabs(p) else os.path.join(cwd, p))

    if canon(git_dir) != canon(common_dir):
        wt_name = os.path.basename(canon(git_dir))
        part += f" {DIM}(wt:{RESET}{CYAN}{wt_name}{RESET}{DIM}){RESET}"
    return part


def context_percent(data):
    ctx = data.get("context_window") or {}
    pct = clamp_pct(ctx.get("used_percentage"))
    if pct is not None and pct > 0:
        return pct
    usage = ctx.get("current_usage") or {}
    size = ctx.get("context_window_size") or 200_000
    used = sum(
        usage.get(k) or 0
        for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    if used and size:
        return clamp_pct(used / size * 100)
    return pct or 0


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print("jay-hud: no stdin data")
        return

    sep = f" {DIM}|{RESET} "

    # 1행: 정체성. 브랜치·워크트리 이름 때문에 길이가 크게 변하는 부분만 모은다.
    head = []
    model = (data.get("model") or {}).get("display_name") or (data.get("model") or {}).get("id")
    if model:
        head.append(f"Model: {model}")

    git_part = git_segment(data)
    if git_part:
        head.append(git_part)

    # 2행: 수치. 게이지 폭이 고정이라 숫자만 변동해 전체 폭이 거의 일정하다.
    body = []
    limits = data.get("rate_limits") or {}
    rate_parts = [
        p
        for p in (
            render_rate_window("5h", limits.get("five_hour"), dim_label=False),
            render_rate_window("wk", limits.get("seven_day"), dim_label=True),
        )
        if p
    ]
    if rate_parts:
        body.append(" ".join(rate_parts))

    ctx_pct = context_percent(data)

    minutes = int(((data.get("cost") or {}).get("total_duration_ms") or 0) // 60_000)
    body.append(f"session:{session_color_for(minutes)}{format_duration(minutes)}{RESET}")

    body.append(f"ctx:{bar(ctx_pct, CTX_BAR_WIDTH)}{color_for(ctx_pct)}{ctx_pct}%{RESET}")

    # head 가 비면(모델·git 둘 다 없음) 빈 행을 만들지 않는다.
    if head:
        print(sep.join(head))
    print(BODY_INDENT + sep.join(body))


if __name__ == "__main__":
    main()
