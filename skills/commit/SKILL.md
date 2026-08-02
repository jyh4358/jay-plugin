---

name: commit

description: 변경사항을 분석하고 지라 태스크 기반 커밋 메시지를 생성하여 커밋

argument-hint: "[jira-id]"

---

  

# Commit Skill

  

변경사항을 분석하여 Conventional Commits 형식의 한국어 커밋 메시지를 자동 생성하고 커밋한다.

  

**동작 개요**: Step 1~3(스테이징 → 커밋 타입·Jira 판별 → 메시지 생성)은 **질문 없이 자동**으로 수행한다. 그 결과를 **Step 4에서 한 번에 보여주고 확인(예/아니오/취소)**받는다. "아니오"면 Step 1~3 중 하나를 골라 수정한 뒤, 영향받는 뒤 단계를 자동 재생성하고 다시 확인하는 루프를 돈다.

  

> 참고: 본문은 Step 4의 항목을 `4.N`(예: 4.1, 4.3, 4.5) 형식으로, 그 하위 절을 `4.5-a/4.5-b/4.5-c` 형식으로 참조한다.

  

## Step 1: 변경사항 확인 및 스테이징 (자동)

  

1. **사전 점검**: `git rev-parse --is-inside-work-tree`로 현재 위치가 git 저장소인지 확인한다. 저장소가 아니면(예: `fatal: not a git repository`) "현재 위치가 git 저장소가 아닙니다." 안내 후 즉시 중단한다.

2. **진행 중 작업 가드**: `git status --porcelain`에 충돌 항목(`UU`/`AA`/`DD`/`AU`/`UA`/`DU`/`UD`)이 있거나, merge/rebase가 진행 중이면(`git rev-parse -q --verify MERGE_HEAD` 성공, 또는 `.git/rebase-merge`·`.git/rebase-apply` 존재) "merge/rebase가 진행 중이거나 충돌이 해결되지 않았습니다. 해결(또는 --abort) 후 다시 실행해주세요." 안내 후 즉시 중단한다. (충돌 마커가 남은 파일을 스테이징·커밋하는 사고 방지)

3. **원격 최신화 확인 (비차단)**: 현재 브랜치에 upstream이 설정되어 있으면 `git fetch --quiet`를 실행하고(실패·오프라인·upstream 없음이면 이 항목 전체를 조용히 건너뜀) `git rev-list --count HEAD..@{upstream}`으로 behind 커밋 수를 구해 기록해둔다. **behind > 0이어도 커밋을 막지 않는다** — 커밋 전 pull은 더러운 작업 트리에서 충돌을 유발할 수 있으므로 하지 않는다. 경고는 Step 4.1에서 표시하고, 정리 순서로 "커밋 후 `git pull --rebase`"를 권장한다.

4. **기존 스테이징 기록**: `git diff --cached --name-only`로 이미 스테이징되어 있던 파일 목록을 기록해둔다. 비어 있지 않으면 사용자가 의도적으로 부분 스테이징해둔 상태일 수 있으므로, 이 목록을 Step 4.1에서 반드시 안내한다.

5. Run `git status` to see all changed files.

6. **자동 스테이징**: `git add -A`를 실행하여 모든 변경(수정·삭제·신규 untracked)을 스테이징한다. `.gitignore`에 등록된 파일은 자동으로 제외된다. 서브디렉토리에서 실행해도 **리포지토리 전체**가 스테이징된다. **이 단계에서는 질문하지 않는다** — 사용자 동의는 Step 4 확인에서 받는다.

7. **민감 파일 검사**: staged 파일명에서 위험 패턴(`.env*`, `*.pem`, `*.key`, `*.p12`, `*.keystore`, `id_rsa*`, `*credentials*`, `*secret*` 등)을 확인해 기록해둔다. 해당 파일은 Step 4.1 목록에 ⚠️로 표시한다. (파일명 휴리스틱이므로 차단하지 않고 표시만 한다 — 제외는 사용자가 4.5-a에서 결정)

8. Run `git diff --cached` to see the final staged changes.

9. If there are no staged changes at all, inform the user "커밋할 변경사항이 없습니다." and stop.

  

## Step 2: 커밋 타입 및 Jira ID 자동 판별 (자동)

  

1. **커밋 타입 자동 판별**: staged diff 내용을 분석하여 가장 적절한 커밋 타입 하나를 자동으로 선택한다. **질문하지 않는다.**

- 사용 가능한 타입: `feat`, `fix`, `refactor`, `style`, `docs`, `test`, `chore`, `perf`, `ci`

- 타입별 기준:

- `feat`: 새로운 기능 추가

- `fix`: 버그 수정

- `refactor`: 기능 변경 없이 코드 구조 개선

- `style`: 코드 포맷팅, 세미콜론 누락 등

- `docs`: 문서 변경

- `test`: 테스트 추가 또는 수정

- `chore`: 빌드, 설정, 패키지 등 기타 변경

- `perf`: 성능 개선

- `ci`: CI/CD 설정 변경

  

2. **Jira ID 자동 결정** (**질문하지 않는다**, 우선순위: **인자 > 브랜치 추출**):

- 스킬 호출 시 인자로 Jira ID가 전달된 경우 (예: `/commit WEL-3030`), 형식을 검증한 뒤 유효하면 그대로 사용한다.

- 인자가 없으면 현재 브랜치명에서 Jira ID 추출을 시도한다.

- 인자도 없고 브랜치에서도 추출되지 않으면 **Jira ID 없이 진행**한다 (메시지에서 `[JIRA_ID]` 부분 생략).

- Jira task ID 형식: 영문 대문자 프로젝트 키 + 하이픈 + 숫자 (예: `WEL-3030`, `PROJECT-1234`). 인자가 이 형식이 아니면 무시하고 브랜치 추출로 폴백한다.

  

## Step 3: 커밋 메시지 생성 (자동)

  

Step 1에서 확정된 staged diff를 기반으로 자동 생성한다 (**질문하지 않음**):

  

1. **첫째 줄 (제목)**: 변경된 파일들의 전체적인 내용을 한국어로 한 줄 요약.

- Jira ID가 있는 경우: `{type}: [{JIRA_ID}] {한줄 요약}` (예: `feat: [WEL-3030] 게시판 목록 조회 API 개발`)

- Jira ID가 없는 경우: `{type}: {한줄 요약}` (예: `fix: 날짜 파싱 오류 수정`)

- Keep it concise (under 72 characters if possible).

  

2. **추가 내용**: 변경사항을 분석하여 부가 설명이 필요하면 최대 3줄까지 bullet point로 작성.

- Only include if the changes are complex enough to warrant additional explanation.

- 제목과 본문 사이에 반드시 **빈 줄 1개**를 넣는다 (git 컨벤션).

- Format:

```

feat: [WEL-3030] 게시판 목록 조회 API 개발

  

- 페이지네이션 및 검색 필터 추가

- 게시판 카테고리별 조회 기능 구현

- 응답 DTO 정의

```

3. **Co-Authored-By 트레일러**: 메시지 맨 끝에 빈 줄 하나를 두고 `Co-Authored-By: Claude <모델명> <noreply@anthropic.com>` 트레일러를 1개 포함한다 (실행 환경이 정확한 트레일러 문자열을 지정하면 그것을 따른다). 트레일러는 Step 4.1의 메시지 전문 표시에도 포함해 사용자가 커밋 전에 확인할 수 있게 한다.

  

## Step 4: 확인 및 커밋 (확인 분기)

  

1. **종합 결과 표시**: Step 1~3의 결과를 텍스트로 한 번에 보여준다.

- 스테이징된 파일 목록 (`git diff --cached --stat` 결과 또는 파일 목록). Step 1.7에서 기록한 민감 파일은 ⚠️와 함께 "커밋에서 뺄지 확인하세요" 경고를 붙인다.

- Step 1.4에서 기록한 기존 부분 스테이징이 있었다면: "실행 전에 이미 N개 파일이 스테이징되어 있었습니다: {목록} — 지금은 전체 변경과 합쳐져 있으니, 원래 의도대로 일부만 커밋하려면 '아니오, 수정'에서 조정하세요." 안내를 표시한다.

- Step 1.3에서 기록한 behind > 0이면: "현재 브랜치가 원격보다 N커밋 뒤에 있습니다. 커밋은 안전하게 진행할 수 있으며, 커밋 후 `git pull --rebase`로 최신화하는 것을 권장합니다." 경고를 표시한다.

- 선택된 커밋 타입과 Jira ID

- 생성된 커밋 메시지 전문 (Co-Authored-By 트레일러 포함)

  

2. **확인 질문** (`AskUserQuestion`):

```

AskUserQuestion(

header: "커밋 확인",

question: "위 내용(스테이징/타입/메시지)으로 커밋할까요?",

options: [

{ label: "예, 커밋", description: "위 내용 그대로 커밋합니다" },

{ label: "아니오, 수정", description: "스테이징/타입/메시지 중 일부를 수정합니다" },

{ label: "취소", description: "스테이징은 그대로 두고 커밋하지 않은 채 종료합니다" }

]

)

```

  

3. **"예, 커밋" 선택 시**:

- HEREDOC 형식으로 커밋한다:

```bash

git commit -m "$(cat <<'EOF'

{commit message here}

EOF

)"

```

- 성공하면 `git log -1 --oneline`을 실행해 결과를 확인하고 보여준다.

- **커밋 실패 시(pre-commit hook 실패 등)**: 에러 메시지를 사용자에게 보여주고 원인을 안내한다. 그 뒤 아래 순서로 처리한다:

- `git status`로 hook이 파일을 자동 수정(formatter 등)했는지 확인한다. 수정된 파일이 있으면 `git add -A`로 재스테이징하고, 바뀐 내용을 Step 4.1(종합 결과 표시)처럼 다시 보여준다.

- 이어서 `AskUserQuestion`으로 다음 동작을 묻는다:

```

AskUserQuestion(

header: "재시도",

question: "커밋이 실패했습니다. 어떻게 할까요?",

options: [

{ label: "다시 커밋", description: "동일 메시지로 커밋을 재시도합니다" },

{ label: "수정 후 재시도", description: "스테이징/타입/메시지를 다시 조정합니다" },

{ label: "취소", description: "커밋하지 않은 채 종료합니다" }

]

)

```

- "다시 커밋" → 이 단계(4.3)의 커밋을 재실행한다. "수정 후 재시도" → 아래 4.5(아니오, 수정) 루프로 합류한다. "취소" → "커밋을 취소했습니다." 안내 후 중단한다.

- 참고: hook이 자동 생성한 변경(formatter 결과 등)은 4.5-a에서 사용자 원본 변경과 함께 표시된다. 이 변경을 제외해도 재커밋 시 동일 hook이 다시 생성할 수 있으므로, 같은 파일에서 hook 실패가 반복되면 "이 변경은 hook이 자동 생성한 것입니다 — 제외해도 재커밋 시 다시 생성됩니다."라고 1회 안내한다. (모든 재시도는 `AskUserQuestion`으로 게이팅되고 "취소"로 언제든 종료 가능하므로 별도의 강제 중단 조건은 두지 않는다.)

  

4. **"취소" 선택 시**: 스테이징을 변경하지 않은 채 "커밋을 취소했습니다." 안내 후 중단한다.

  

5. **"아니오, 수정" 선택 시**: 어떤 단계를 수정할지 `AskUserQuestion`으로 묻는다:

```

AskUserQuestion(

header: "수정 항목",

question: "어떤 항목을 수정할까요?",

options: [

{ label: "스테이징 (Step 1)", description: "스테이징할 파일을 다시 조정합니다" },

{ label: "커밋 타입/Jira (Step 2)", description: "커밋 타입 또는 Jira ID를 다시 선택합니다" },

{ label: "커밋 메시지 (Step 3)", description: "커밋 메시지 내용을 다시 다듬습니다" }

]

)

```

선택한 항목을 아래와 같이 수정한 뒤, **영향받는 뒤 단계를 자동 재생성**하고 다시 **Step 4.1~4.2(종합 결과 표시 및 확인)**로 돌아간다.

  

### 4.5-a. 스테이징 (Step 1) 수정

- 현재 스테이징된 파일 목록을 **텍스트로 보여준 뒤**, `AskUserQuestion`으로 조정 방식을 받는다. 파일 목록은 **옵션이 아니라 question 본문/직전 텍스트로 표시**하여 옵션 개수가 파일 수에 영향받지 않게 한다 (AskUserQuestion options는 항상 2~4개여야 함):

```

AskUserQuestion(

header: "스테이징 수정",

question: "스테이징을 어떻게 조정할까요?\n{staged 파일 목록을 본문에 텍스트로 표시}",

options: [

{ label: "모두 유지", description: "현재 스테이징을 그대로 둡니다" },

{ label: "일부 제외", description: "스테이징에서 뺄(unstage) 파일명을 직접 입력합니다" },

{ label: "전부 unstage", description: "모든 파일을 스테이징에서 제외합니다" },

{ label: "파일 추가", description: "스테이징에 새로 추가할 파일명을 직접 입력합니다 (.gitignore 대상 포함)" }

]

)

```

- **모두 유지**: unstage 없이 그대로 진행한다 (다른 항목을 잘못 골랐을 때의 탈출구).

- **일부 제외**(unstage 전용): 후속 자유 입력으로 제외할 파일명을 받는다. **한 줄에 한 파일씩** 입력받고(공백 포함 경로를 안전하게 처리하기 위함), 각 줄을 trim한 뒤 빈 줄은 무시한다. 각 파일을 `git reset -- <file>`로 unstage 한다. (새 파일 추가는 이 옵션이 아니라 "파일 추가"로 분리한다.)

- **전부 unstage**: `git reset`으로 전부 제외한다.

- **파일 추가**: 후속 자유 입력으로 추가할 파일명을 **한 줄에 한 파일씩** 받아 각 파일을 `git add <file>`로 스테이징한다.

- (참고) `git reset` / `git reset -- <file>`는 HEAD가 없는 최초 커밋 상황에서도 동작한다. `git restore --staged`는 HEAD가 없으면 실패하므로 사용하지 않는다.

- **파일 처리 에러**: 제외/추가 대상 파일이 존재하지 않거나(오타) 경로가 맞지 않으면 그 사실을 알리고 해당 항목만 다시 입력받는다. 추가 대상 파일이 `.gitignore` 대상이라 `git add`가 무시한 경우, 강제 추가 여부를 `AskUserQuestion`(옵션: "강제 추가" / "이 파일 건너뛰기")으로 묻는다. "강제 추가" → `git add -f <file>`로 추가한다. "이 파일 건너뛰기"(또는 Other 거부) → 그 파일만 빼고 나머지 입력 처리를 계속한다.

- **자동 재생성**: 스테이징이 바뀌었으므로 `git diff --cached`를 재확인한 뒤 **민감 파일 검사(Step 1.7)를 다시 수행**하고, **커밋 타입을 diff 기반으로 다시 판별**하고 **커밋 메시지(Step 3)를 다시 생성**한다. 단, **Jira ID는 diff와 무관하므로 현재 확정값(사용자가 4.5-b에서 직접 입력/건너뛰기로 정한 값 포함)을 그대로 보존**하며 재결정하지 않는다.

- staged 변경이 모두 없어지면 "커밋할 변경사항이 없습니다." 안내 후 중단한다.

  

### 4.5-b. 커밋 타입/Jira (Step 2) 수정

- 커밋 타입을 `AskUserQuestion`으로 다시 선택받는다. 1번은 추천 타입 (Recommended), 2~4번은 diff 기반 차순위 3개, 나머지는 "Other"로 직접 입력:

```

AskUserQuestion(

header: "커밋 타입",

question: "커밋 타입을 선택해주세요:",

options: [

{ label: "{추천타입} (Recommended)", description: "{추천타입 설명}" },

{ label: "{차순위타입1}", description: "{설명}" },

{ label: "{차순위타입2}", description: "{설명}" },

{ label: "{차순위타입3}", description: "{설명}" }

]

)

```

- 이어서 Jira ID를 `AskUserQuestion`으로 다시 선택받는다. **옵션은 상황에 따라 구성하되 항상 2~4개를 유지**하며, Step 2의 우선순위(**인자/확정값 > 브랜치 추출값**)를 따른다:

- 현재 확정 Jira ID가 있으면(인자 또는 이전 선택 유래) 그 값을 `{현재 Jira ID} 유지` **첫 번째** 옵션으로 둔다.

- 브랜치에서 추출된 값이 있고 확정값과 다르면 그 값을 다음 옵션으로 함께 둔다.

- 확정값이 없고 브랜치에서만 추출되면 추출값을 첫 번째 옵션으로 둔다.

- 추출값·확정값이 하나도 없으면 값 옵션을 생략한다.

- 마지막에 항상 `건너뛰기`, `직접 입력`을 둔다.

```

AskUserQuestion(

header: "Jira ID",

question: "지라 태스크 번호를 선택해주세요:",

options: [

{ label: "{확정/추출 Jira ID}", description: "현재 값 사용 (확정값/추출값이 있을 때만 포함)" },

{ label: "건너뛰기", description: "Jira ID 없이 커밋합니다" },

{ label: "직접 입력", description: "다른 태스크 번호를 입력합니다 (자동 추가되는 \"Other\"와 동일한 자유 입력 경로이며, 값 옵션이 없을 때 최소 2개 옵션을 보장하기 위해 명시적으로 둔다)" }

]

)

```

- "직접 입력" 또는 "Other" 값은 Jira ID 형식(`WEL-3030` 등)을 검증하고, 형식이 아니면 다시 입력을 요청한다. "건너뛰기" 선택 시 메시지에서 `[JIRA_ID]` 부분을 생략한다.

- **자동 재생성**: 타입/Jira가 바뀌었으므로 **커밋 메시지(Step 3)를 다시 생성**한다.

  

### 4.5-c. 커밋 메시지 (Step 3) 수정

- 사용자에게 어떻게 고치면 좋을지 **피드백을 받는다** (예: "더 짧게", "본문 빼줘", "○○ 내용 추가"). 피드백을 반영하여 메시지를 **재생성**한다.

- 단, 피드백이 수정 의도가 아니라 취소/포기 의사이면 Rules의 전역 규칙에 따라 스테이징을 변경하지 않은 채 안내 후 중단한다.

- 뒤 단계가 없으므로 추가 재생성은 하지 않는다.

  

6. 위 수정·재생성 후 **Step 4.1~4.2로 돌아가 다시 표시·확인**한다. **"예, 커밋"(커밋 실행) 또는 "취소"(종료)가 선택될 때까지** 이 루프를 반복한다.

  

## Rules

  

- Write the summary in Korean.

- Keep the first line concise and meaningful.

- Additional bullet points should only be added when the changes are non-trivial.

- Do NOT push to remote — only commit locally. `git fetch`(Step 1.3)는 조회 전용이므로 허용된다. pull/rebase도 실행하지 않는다 — behind 상태는 경고로만 안내한다.

- 커밋 메시지에는 Co-Authored-By 트레일러를 포함한다 (Step 3.3).

- **Step 1~3은 질문 없이 자동으로 수행하고, 사용자 동의는 Step 4 확인(예/아니오/취소)에서 한 번에 받는다.** Step 4에서 staged 파일 목록을 반드시 보여준 뒤 "예"를 받았을 때만 커밋한다.

- 자동 스테이징은 `git add -A`로 수행한다 (`.gitignore` 제외 파일은 자동 제외).

- "아니오" 분기에서 앞 단계(스테이징/타입)를 수정하면, 영향받는 뒤 단계(타입·메시지)를 자동으로 다시 생성한 뒤 재확인한다. 단, Jira ID는 diff와 무관하므로 스테이징 수정으로는 재결정하지 않고 보존한다.

- unstage에는 `git reset`(또는 `git reset -- <file>`)을 사용한다. `git restore --staged`는 HEAD가 없는 최초 커밋 상황에서 실패하므로 쓰지 않는다.

- 확인/수정/재시도 루프 어디서든 사용자가 "취소"(또는 Other 자유 입력으로 커밋 포기 의사)를 표하면, 스테이징을 변경하지 않은 채 안내 메시지 출력 후 중단한다.

- `AskUserQuestion`의 options는 항상 2~4개여야 한다. 동적 목록(예: staged 파일)을 옵션으로 나열하지 말고, 목록은 question 본문/텍스트로 보여주고 옵션은 고정된 선택지로 구성한다.