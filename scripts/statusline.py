#!/usr/bin/env python3
"""jay-plugin statusline — Claude Code 상태줄 렌더러.

Claude Code가 statusline 명령의 stdin으로 넘겨주는 JSON만으로 렌더링한다
(네트워크 호출·외부 의존성 없음).

  Model: Fable 5 | 5h:[█░░░░░░░]4%(4h48m) wk:[█░░░░░░░]17%(5d15h) | session:3m | ctx:[█░░░░░░░░░]7%

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
    segments = []

    model = (data.get("model") or {}).get("display_name") or (data.get("model") or {}).get("id")
    if model:
        segments.append(f"Model: {model}")

    git_part = git_segment(data)
    if git_part:
        segments.append(git_part)

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
        segments.append(" ".join(rate_parts))

    ctx_pct = context_percent(data)

    minutes = int(((data.get("cost") or {}).get("total_duration_ms") or 0) // 60_000)
    if minutes > 120 or ctx_pct > 85:
        session_color = RED
    elif minutes > 60 or ctx_pct > 70:
        session_color = YELLOW
    else:
        session_color = GREEN
    segments.append(f"session:{session_color}{minutes}m{RESET}")

    segments.append(f"ctx:{bar(ctx_pct, CTX_BAR_WIDTH)}{color_for(ctx_pct)}{ctx_pct}%{RESET}")

    print(sep.join(segments))


if __name__ == "__main__":
    main()
