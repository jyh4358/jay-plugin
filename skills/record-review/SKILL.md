---
name: record-review
description: Obsidian vault 'My Track Record'의 월간 유지보수. 작업 노트의 resume·impact 재평가와 작업·학습 노트 전반의 frontmatter·wikilink 무결성 점검을 리포트 → 사용자 확인 → 반영 순서로 수행한다. 사용자가 "/record-review", "기록 점검", "vault 정리", "이력서 후보 재평가" 같이 쌓인 기록을 정리하려는 신호를 줄 때 사용. 새 작업 기록은 record 스킬 담당 — 이 스킬은 기존 노트만 다룬다.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion
user-invocable: true
---

# /record-review — 쌓인 기록 점검·정리

record가 "쓰는" 스킬이라면 이것은 "관리하는" 스킬이다. 목적은 두 가지:

1. **이력서 후보 품질** — resume·impact가 낡은 평가로 남으면 이력서 쓸 때 재작업이 된다.
2. **스키마·링크 무결성** — frontmatter 일관성과 실링크가 검색·대시보드·그래프 품질을 결정한다.

## 0. 설정

1. `~/.claude/record-config.json`에서 vaultPath를 읽는다 (record 스킬과 공유). 없으면 vault 경로를 물어 `{ "vaultPath": "<절대 경로>" }`로 생성한다 — record가 쓰는 다른 키(defaultOrg)는 그 스킬이 필요할 때 채운다.
2. vault 검증: `99-템플릿/Worklog.md` 존재 확인.
3. vault가 git 저장소면 시작 전 `git pull`.
4. 날짜는 전부 bash(`date +%F` 등)로 다룬다 — 암산 금지.

## 1. 점검 — 수정 없이 현황만 수집

`10-회사/`, `20-개인/` (projects/ 포함) 전체를 두 축으로 스캔한다. `30-학습/`의 학습 노트는 B축(무결성)만 적용한다:

### A. resume·impact 재평가 후보
- worklog 노트 중:
  - `impact: high`인데 `resume: false` → 승격 후보
  - `resume: true`인데 '어필 포인트'가 비었거나 행동동사·정량 성과 없이 빈약 → 보강 또는 강등 후보
  - impact 판정이 본문 성과와 안 맞는 것 (예: 정량 성과가 명시돼 있는데 low)

### B. 무결성
- frontmatter: 필수 필드 누락(summary 빈 값, updated·date_end 없음), worklog인데 `status: done`이 아닌 것(worklog는 항상 done — `ongoing`은 프로젝트 허브 전용), 스키마 밖 값(work_type·impact 오타)
- 학습 노트(type: learning) frontmatter: summary 빈 값, date·updated 없음, 스키마 밖 필드(status·impact·resume 등 worklog 전용 필드가 섞인 것)
- 링크 양방향: worklog의 `project` 값 ↔ `projects/<이름>.md` 허브 존재 ↔ 허브 '작업 목록'에 해당 노트 링크 ↔ worklog `## 관련`의 `[[<프로젝트명>]]` — 어느 방향이든 끊긴 것
- 깨진 wikilink: 허브 '작업 목록', `## 관련`, 학습 노트의 `관련:` 줄 등에서 실제 파일이 없는 링크

## 2. 리포트

축별 결과를 표로 보여준다. **문제 없는 축도 "이상 없음"으로 명시한다** (침묵은 점검 안 한 것과 구분이 안 된다). 각 항목에 판단 근거(마지막 updated, 현재 값 vs 제안 값)를 붙인다.

## 3. 처리 — 사용자 확인 없이 아무것도 고치지 않는다

- **resume·impact**: 변경 제안 + 근거를 보여주고 승인받은 것만 frontmatter 수정. 어필 포인트 보강은 초안을 보여주고 승인받는다.
- **무결성**: 기계적 수정(누락 링크 추가, 스키마 오타 값 교정 등)은 목록을 한 번에 보여주고 일괄 승인으로 처리해도 된다. 단 **`date_end` 보충은 기계적이지 않다** — 실제 완료일은 추정 대상이므로 노트별로 근거(진행 이력 마지막 날짜, updated)와 제안 값을 보여주고 개별 확인받는다.
- 모든 수정은 Read 후 Edit 부분 수정 + `updated` 갱신 (통째 덮어쓰기 금지).

## 4. 마무리

- 처리 요약을 보고한다: 재평가 N건 / 무결성 수정 N건 / 보류 N건.
- vault가 git 저장소면 커밋·push 여부를 물어 진행한다.
- 이 지시문 내용을 노트에 옮겨 적지 않는다.
