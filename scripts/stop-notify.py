#!/usr/bin/env python3
"""Claude Code Stop/Notification 훅: 세션 제목을 포함한 macOS 알림을 띄운다.

stdin 으로 받은 hook JSON 의 transcript_path 에서 세션 제목
(custom-title 우선, 없으면 ai-title)을 추출해 알림 제목으로 쓰고,
이벤트에 따라 내용을 달리한다:
  - Stop         → "응답이 완료되었습니다" (소리: Glass)
  - Notification → 입력 대기 사유(권한 요청·질문 등, hook JSON 의 message)
                   (소리: Ping — 완료 알림과 귀로 구분)
"""
import json
import subprocess
import sys


def resolve_title(transcript_path):
    """transcript JSONL 에서 최신 custom-title -> ai-title 순으로 제목을 찾는다."""
    custom = None
    ai = None
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                # 빠른 사전 필터 (전체 파싱 비용 절감)
                if "title" not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "custom-title" and obj.get("customTitle"):
                    custom = obj["customTitle"]
                elif obj.get("type") == "ai-title" and obj.get("aiTitle"):
                    ai = obj["aiTitle"]
    except (OSError, TypeError):
        pass
    return custom or ai or "Claude Code"


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    title = resolve_title(data.get("transcript_path"))

    if data.get("hook_event_name") == "Notification":
        # 입력 대기: 권한 승인, AskUserQuestion, 60초 유휴 등 — 사유가 message 로 옴
        message = data.get("message") or "입력을 기다리고 있습니다"
        sound = "Ping"
    else:
        message = "응답이 완료되었습니다"
        sound = "Glass"

    # AppleScript 문자열 안에서 따옴표/역슬래시가 깨지지 않도록 이스케이프
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'display notification "{esc(message)}" '
        f'with title "{esc(title)}" sound name "{sound}"'
    )
    subprocess.run(["osascript", "-e", script], check=False)


if __name__ == "__main__":
    main()
