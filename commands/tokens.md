---
description: 현재 세션에서 토큰(구독 플랜)을 가장 많이 쓴 질문과 이유 분석
argument-hint: [선택: 추가 질문]
allowed-tools: Bash(python3:*)
---
아래는 현재 세션(`$CLAUDE_CODE_SESSION_ID`)의 토큰 사용 랭킹이야 — **가중 사용량**(`가중≈`) 많은 순으로, 각 턴의 구성과 주요 도구 유입 포함:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plan_usage.py" --rank "$CLAUDE_CODE_SESSION_ID"`

가중 사용량 읽는 법: Opus 입력 토큰으로 환산한 단일 지수야. 모델 티어(haiku 0.2x / sonnet 0.4~0.6x / opus 1x / fable 2x), 출력 5x, 캐시읽기 0.1x 가중치가 반영돼 있어서, 생 토큰(소진)보다 플랜 소모를 더 정직하게 반영해. 소진은 작은데 가중이 큰 턴은 캐시 재입력이나 비싼 모델(fable) 때문이야.

위 데이터를 근거로 한국어로 답해줘:
- 가중 사용량이 가장 큰 질문 상위 3개(전체가 3개 미만이면 전부)를 가중·소진량과 함께
- 각 질문이 **왜** 무거웠는지 해석: 구성(질문+시스템 / 도구결과 / 루프재입력 / 출력)과 주요 도구 유입(파일읽기·검색·Bash·서브에이전트 등)을 근거로. 소진과 가중의 괴리가 큰 턴은 그 원인(캐시 재입력, 모델 가중치)도 짚어줘
- 5시간 한도 최적화에 도움이 될 짧은 팁이 있으면 덧붙여

만약 위 데이터가 비어 있거나 오류이면, 직접 Bash로 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plan_usage.py" --rank "$CLAUDE_CODE_SESSION_ID"` 를 실행해서 가져와.

주의: 이 수치는 로컬 근사치이고, 플랜 실제 소진율의 권위값은 `/usage`야.

사용자 추가 요청(있으면 우선 반영): $ARGUMENTS
