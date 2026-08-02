# 🧰 jay-plugin

**Jay's Claude Code toolbox** — a personal collection of hooks, commands, skills, and agents for everyday Claude Code workflows, packaged as a single plugin so every machine stays in sync.

Instead of copying install scripts between machines, register the marketplace once and sync everything with `git push` → plugin update.

[English](#installation) | [한국어](#한국어-안내)

## Installation

```
/plugin marketplace add jyh4358/jay-plugin
/plugin install jay-plugin@jay-plugin
```

> ⚠️ If you previously installed these hooks manually, remove the old entries
> (`Stop` hooks in `~/.claude/settings.json` and `~/.claude/commands/tokens.md`)
> to avoid double execution.

**Requirements:** Python 3.9+ · macOS (for notifications only — the token reporter works everywhere)

## Components

| Type | Name | Description | Status |
|---|---|---|---|
| Hook (Stop) | **plan-usage** | Per-turn token usage report as a system message after every response | ✅ |
| Hook (Stop · Notification) | **stop-notify** | macOS notification on response completion (*Glass*) and when Claude is waiting for your input — permission requests, questions (*Ping*) | ✅ |
| Command | **/tokens** | Ranks the current session's turns by weighted usage and explains *why* the heavy ones were heavy | ✅ |
| Statusline | **statusline** | Model · git branch/worktree · 5h/weekly plan usage bars with reset timers · session time · context usage | ✅ |
| Skill | **/commit** | Analyzes staged changes, generates a Korean Conventional-Commits message (optional Jira ID), confirms, then commits | ✅ |
| Skill | **/record** | Records session work into the *My Track Record* Obsidian vault as resume-ready task notes — why/how/result structure, short interview, confidentiality filter | ✅ |
| Agents | — | (planned) | 🚧 |

New components go into their directory (`hooks/` `commands/` `skills/` `agents/`) — push, then update the plugin on each machine.

## plan-usage — token usage reporter

Shows what every turn actually consumed, right after it finishes:

```
━━━━━━ 이 턴 플랜 토큰 ━━━━━━
Q: 사용하는 모델 기준으로 출력되게 할 수 있어?
모델: claude-opus-5
소진(신규) ~62,948   재사용(캐시) 10,071,993   가중≈1.21M (Opus입력 환산)
  ├ 출력 생성 24,287
  └ 신규 입력 38,661
       질문+시스템 3,059 / 도구결과 5,449 / 루프재입력 30,153
  도구별 유입(추정):
    Read        ~   3,644  (1회)
세션 누적: 소진 ~138,536  가중≈2.25M  (9턴)
```

### Key concepts

- **Weighted usage** — a single index in Opus-input-token equivalents.
  Reflects model tier (haiku 0.2x / sonnet 0.4–0.6x / opus 1x / fable 2x), output 5x, cache reads 0.1x —
  a more honest proxy for plan consumption than raw token counts.
- **Subagent-aware** — reads `agent-*.jsonl` transcripts and attributes their usage to the turn that spawned them.
- **Ledger** — `~/.claude/token-usage/<session>.json`, ~0.5 KB per turn.
  Stores numbers only (plus the first 200 chars of each question) — never conversation content.
- **Future-proof pricing** — built-in table → family inference for brand-new models (opus/sonnet/haiku/fable)
  → user override via `~/.claude/token-usage/prices.json`. No code edits when models or prices change.

### CLI reference

```bash
SCRIPT=~/.claude/plugins/…/jay-plugin/scripts/plan_usage.py   # installed path

python3 $SCRIPT --rank <session-id>   # recomputed ranking for one session
python3 $SCRIPT --rank-all            # all sessions (--since YYYY-MM-DD / --json)
python3 $SCRIPT --log  <session-id>   # read the stored ledger
python3 $SCRIPT --repair              # reconcile ledger against transcripts (--yes to apply, keeps .bak)
```

### Notes

- Figures are local approximations. The authoritative plan-usage number is `/usage`.
- Once Claude Code's transcript retention (default 30 days) cleans a session,
  recomputation (`--rank`/`--repair`) is no longer possible — the ledger keeps the last known values.

## statusline — plan usage HUD

```
Model: Fable 5 | branch:main | 5h:[█░░░░░░░]7%(4h32m) wk:[█░░░░░░░]17%(5d15h) | session:6m | ctx:[█░░░░░░░░░]9%
```

Renders entirely from the JSON Claude Code pipes to the statusline command — no network calls,
no dependencies (rate limits require a subscription/OAuth login; the segment is skipped for API-key users).
Colors: green → yellow (≥70%) → red (≥90%).
Inside a linked git worktree the branch segment becomes `branch:feat-x (wt:feat-x)`.

Plugins can't register a statusline automatically, so add this once per machine to `~/.claude/settings.json`
(after installing the plugin):

```json
"statusLine": {
  "type": "command",
  "command": "python3 \"${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/marketplaces/jay-plugin/scripts/statusline.py\""
}
```

## stop-notify — macOS notifications

Two distinct sounds so you can tell them apart without looking:

| Event | Sound | Meaning |
|---|---|---|
| Response finished (`Stop`) | *Glass* | done — come check the result |
| Waiting for you (`Notification`) | *Ping* | action needed — permission request, question, or idle prompt |

The notification title is the session title (custom title first, then AI title).

---

## 한국어 안내

**Jay의 Claude Code 툴박스** — 일상 워크플로에서 반복해 쓰는 훅·커맨드·스킬·에이전트를
하나의 플러그인으로 묶어 여러 맥에서 동일하게 쓰기 위한 개인 컬렉션.
수동 설치 스크립트를 기기마다 옮기는 대신, 마켓플레이스 등록 한 번으로 설치하고
`git push` → 플러그인 업데이트로 모든 기기를 동기화한다.

### 설치

```
/plugin marketplace add jyh4358/jay-plugin
/plugin install jay-plugin@jay-plugin
```

> ⚠️ 이전에 수동으로 설치했던 맥이라면 다음을 제거해야 이중 실행되지 않는다:
> `~/.claude/settings.json` 의 Stop 훅 2개(plan_usage, stop-notify), `~/.claude/commands/tokens.md`

### 구성 요소

| 종류 | 이름 | 설명 |
|---|---|---|
| 훅 (Stop) | plan-usage | 매 턴 종료 시 토큰 사용량 리포트를 시스템 메시지로 표시 |
| 훅 (Stop·Notification) | stop-notify | 응답 완료(Glass음), 입력 대기 — 권한 요청·질문 — 시(Ping음) macOS 알림 |
| 커맨드 | `/tokens` | 현재 세션의 가중 사용량 랭킹 + 왜 무거웠는지 분석 |
| 상태줄 | statusline | 모델 · git 브랜치/워크트리 · 5h/주간 플랜 사용량 막대(리셋 타이머) · 세션 시간 · 컨텍스트 사용률 표시 |
| 스킬 | `/commit` | 변경사항 분석 → Conventional Commits 한국어 커밋 메시지 생성(Jira ID 지원) → 확인 후 커밋 |
| 스킬 | `/record` | 세션에서 한 작업을 Obsidian vault(My Track Record)에 무엇을/왜/어떻게/성과 구조의 작업 노트로 기록 — 부족한 맥락 인터뷰 + 회사 기밀 보안 필터 |

### 주요 개념

- **가중 사용량**: Opus 입력 토큰으로 환산한 단일 지수.
  모델 티어(haiku 0.2x / sonnet 0.4~0.6x / opus 1x / fable 2x), 출력 5x, 캐시읽기 0.1x 반영.
- **서브에이전트 포함**: `agent-*.jsonl` 을 읽어 각 턴에 시각 기준으로 귀속.
- **장부**: `~/.claude/token-usage/<세션ID>.json` — 턴당 ~0.5KB 요약만 저장
  (대화 본문 없음, 질문 앞 200자만).
- **단가(가중치 원천)**: 내장 표 → 계열 추정 → `~/.claude/token-usage/prices.json` 오버라이드 순.
  새 모델이 나와도 계열로 자동 추정하고, 가격이 다르면 prices.json 에 한 줄 추가.

### 주의

- 수치는 로컬 근사치다. 플랜 실제 소진율의 권위값은 `/usage`.
- transcript(`~/.claude/projects/**`)가 보존 기간(기본 30일)으로 정리되면
  해당 세션의 재계산은 불가능해지고, 장부의 기존 값만 남는다.

## License

[MIT](LICENSE)
