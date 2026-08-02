#!/usr/bin/env python3
"""턴별 구독-플랜 토큰 사용량 + '어디에 썼는지' 분해 리포트.

용법:
  python3 plan_usage.py                 # 최근 세션 자동 감지, 마지막 턴
  python3 plan_usage.py <transcript>    # 특정 JSONL의 마지막 턴
  python3 plan_usage.py --all [<t>]     # 모든 턴을 순회 출력(검증용)
  python3 plan_usage.py --log [<sid>]   # 저장된 누적 로그 출력
  python3 plan_usage.py --rank [<sid>]  # 한 세션을 transcript에서 재계산
  python3 plan_usage.py --rank-all      # 모든 세션 재계산 표 (--since YYYY-MM-DD / --json)
  python3 plan_usage.py --repair        # 저장 누적값을 재계산값으로 교정 (--yes 로 실제 적용)
  (Stop 훅에서 실행되면 stdin JSON의 transcript_path/session_id 사용)

가중 사용량:
  화면에는 달러 대신 '가중≈NK/M' (Opus 입력 토큰 환산)을 표기한다.
  모델 티어·출력 5x·캐시읽기 0.1x 가중치를 반영한 단일 비교 지수다.
  가중치 원천은 아래 단가표이고, 내부 저장(rec["cost"])은 달러 지수 그대로다.

단가(=가중치 원천):
  내장 표 → 계열 추정(opus/sonnet/haiku/fable) → Opus 5 기본값 순으로 결정.
  ~/.claude/token-usage/prices.json 으로 코드 수정 없이 덮어쓸 수 있다.
    {"claude-opus-6": [7.5, 37.5], "claude-sonnet-7": {"input": 4, "output": 20}}

측정 방식
  - 턴 = 마지막 '사용자 텍스트 메시지'부터 끝까지 (그 사이 모든 도구 호출/응답/사고 포함)
  - 출력/신규입력/캐시읽기/비용: message.usage 에서 정확 집계
      단가는 message.model 을 읽어 모델별로 적용(한 턴에 모델이 섞여도 호출별로 계산)
  - 도구별 '컨텍스트 유입': 델타법으로 실측 추정
      call i 의 도구결과 토큰 ≈ new_input(call i+1) − output(call i)
      한 스텝에 병렬 도구가 여럿이면 결과 문자열 길이 비율로 배분
  - Write/Edit '생성': 도구 입력(new_string/content)의 토큰 추정(출력측 비용)
"""
import json, sys, os, glob, datetime, shutil
from collections import defaultdict

# 모델별 기본 단가 (입력, 출력) $/1M — claude-api 스킬 기준.
# 캐시 단가는 입력가에서 파생: 쓰기 5m 1.25x / 쓰기 1h 2x / 읽기 0.1x
BASE_PRICE = {
    "claude-fable-5":    (10.0, 50.0),
    "claude-mythos-5":   (10.0, 50.0),
    "claude-opus-5":     ( 5.0, 25.0),
    "claude-opus-4-8":   ( 5.0, 25.0),
    "claude-opus-4-7":   ( 5.0, 25.0),
    "claude-opus-4-6":   ( 5.0, 25.0),
    "claude-opus-4-5":   ( 5.0, 25.0),
    "claude-sonnet-5":   ( 3.0, 15.0),   # 도입가는 INTRO 참고
    "claude-sonnet-4-6": ( 3.0, 15.0),
    "claude-sonnet-4-5": ( 3.0, 15.0),
    "claude-haiku-4-5":  ( 1.0,  5.0),
}
# 한시적 도입가: (모델, 종료일 YYYY-MM-DD, 입력, 출력)
INTRO = [("claude-sonnet-5", "2026-08-31", 2.0, 10.0)]
# fast 모드 (usage.speed == "fast") — Opus 5 / Opus 4.8 만 지원
FAST_PRICE = {"claude-opus-5": (10.0, 50.0), "claude-opus-4-8": (10.0, 50.0)}
DEFAULT_MODEL = "claude-opus-5"   # 계열도 못 알아볼 때 최후 대체 단가

# 계열 추정 단가: 표에 없는 새 모델이 나와도 이름의 계열로 티어를 추정한다.
# (예: claude-opus-6 -> opus 티어) 코드 수정 없이 대략 맞는 값이 나오고,
#  출력에 '계열추정'으로 표시되므로 값이 틀리면 아래 prices.json 으로 덮어쓴다.
FAMILY_PRICE = [("fable", (10.0, 50.0)), ("mythos", (10.0, 50.0)),
                ("opus",  ( 5.0, 25.0)), ("sonnet", ( 3.0, 15.0)),
                ("haiku", ( 1.0,  5.0))]
INFERRED = set()                  # 계열 추정으로 계산한 model id

# 사용자 단가 오버라이드. 코드를 고치지 않고 여기에 모델을 추가/수정한다.
#   ~/.claude/token-usage/prices.json
#   {"claude-opus-6": [7.5, 37.5], "claude-sonnet-6": {"input": 4, "output": 20}}
PRICE_OVERRIDE = os.path.expanduser("~/.claude/token-usage/prices.json")

def _load_override():
    try:
        with open(PRICE_OVERRIDE) as f: d = json.load(f)
        out = {}
        for k, v in (d or {}).items():
            if isinstance(v, (list, tuple)) and len(v) == 2:
                out[k] = (float(v[0]), float(v[1]))
            elif isinstance(v, dict) and "input" in v and "output" in v:
                out[k] = (float(v["input"]), float(v["output"]))
        return out
    except Exception:
        return {}   # 파일 없음/깨짐 → 내장 표만 사용

def family_price(m):
    s = str(m).lower()
    for kw, p in FAMILY_PRICE:
        if kw in s: return p
    return None
# Claude Code가 만드는 클라이언트측 가짜 어시스턴트 메시지(한도 안내·중단 등).
# usage가 전부 0인 미청구 레코드라 단가 0으로 처리하고 모델 집계에서도 제외한다.
PSEUDO = {"<synthetic>"}
UNKNOWN = set()                   # 단가표에 없던 model id (출력에 경고)

def is_pseudo(m):
    return bool(m) and str(m).strip() in PSEUDO

BASE_PRICE.update(_load_override())   # 사용자 오버라이드가 내장 표를 덮어씀
CH_PER_TOK = 4  # 도구결과 토큰 추정용 (문자수/토큰). 배분에는 상수라 무관.

def norm_model(m):
    """transcript의 model 문자열을 BASE_PRICE 키로 정규화. 못 맞추면 None."""
    if not m: return None
    m = str(m).strip()
    for p in ("us.anthropic.", "eu.anthropic.", "apac.anthropic.", "anthropic."):
        if m.startswith(p):
            m = m[len(p):]; break
    m = m.split("[", 1)[0]                      # claude-opus-5[1m] -> claude-opus-5
    if m in BASE_PRICE: return m
    hits = [k for k in BASE_PRICE if m.startswith(k)]   # 날짜 접미사 등
    return max(hits, key=len) if hits else None

def rates(model, fast=False):
    """model id -> {input, output, cw5, cw1, cr} ($/1M)"""
    if is_pseudo(model):
        return {"input": 0.0, "output": 0.0, "cw5": 0.0, "cw1": 0.0, "cr": 0.0}
    key = norm_model(model)
    if key is not None:                       # 1) 표(내장+오버라이드)에 있는 모델
        inp, out_ = BASE_PRICE[key]
    else:
        fp = family_price(model) if model else None
        if fp:                                # 2) 처음 보는 모델 → 이름으로 계열 추정
            inp, out_ = fp
            INFERRED.add(str(model))
        else:                                 # 3) 계열도 모름 → 최후 대체
            if model: UNKNOWN.add(str(model))
            key = DEFAULT_MODEL
            inp, out_ = BASE_PRICE[key]
    today = datetime.date.today().isoformat()
    for m, until, i2, o2 in INTRO:
        if key == m and today <= until: inp, out_ = i2, o2
    if fast and key in FAST_PRICE: inp, out_ = FAST_PRICE[key]
    return {"input": inp, "output": out_, "cw5": inp*1.25, "cw1": inp*2, "cr": inp*0.1}

# 표시 단위: '가중 사용량' = Opus 입력 토큰 환산.
# 내부 계산(rec["cost"] 등)은 달러 지수를 그대로 쓰고, 화면에 보일 때만 환산한다.
#   가중치 예: opus 입력 1.0x / 출력 5.0x, haiku 0.2x/1.0x, fable 2x/10x, 캐시읽기 0.1x
OPUS_UNIT = 5.0   # $/1M — 가중 1.0 의 기준(Opus 입력 단가)

def wtok(dollars):
    """달러 지수 -> Opus 입력 환산 토큰 수"""
    return dollars / OPUS_UNIT * 1e6

def fmt_tok(n):
    if n >= 1e9: return f"{n/1e9:.2f}B"
    if n >= 1e6: return f"{n/1e6:.2f}M"
    if n >= 1e3: return f"{n/1e3:.1f}K"
    return f"{n:.0f}"

def fmt_w(dollars):
    return fmt_tok(wtok(dollars))

def model_label(models):
    """{모델: 호출수} -> 'claude-opus-5' 또는 'claude-opus-5 x3, claude-haiku-4-5 x1'"""
    if not models: return "?"
    items = sorted(models.items(), key=lambda x: -x[1])
    if len(items) == 1: return items[0][0]
    return ", ".join(f"{k} x{v}" for k, v in items)

def get_source():
    argv = [a for a in sys.argv[1:] if a != "--all"]
    if argv and os.path.exists(argv[0]):
        return argv[0], {}
    hook = {}
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            try: hook = json.loads(raw)
            except Exception: hook = {}
    if hook.get("transcript_path"):
        return hook["transcript_path"], hook
    files = [f for f in glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True)
             if not os.path.basename(f).startswith("agent-")]  # 서브에이전트 transcript 제외
    return (max(files, key=os.path.getmtime) if files else None), hook

def est_tokens(content):
    if content is None: return 0
    if isinstance(content, str): return len(content) // CH_PER_TOK
    if isinstance(content, dict):
        if content.get("type") == "text": return len(content.get("text", "")) // CH_PER_TOK
        if "content" in content: return est_tokens(content["content"])
        return len(json.dumps(content, ensure_ascii=False)) // CH_PER_TOK
    if isinstance(content, list): return sum(est_tokens(b) for b in content)
    return 0

def U(u, k): return u.get(k, 0)
def new_in(u):  return U(u, "input_tokens") + U(u, "cache_creation_input_tokens")
def out(u):     return U(u, "output_tokens")
def cread(u):   return U(u, "cache_read_input_tokens")
def cost(u, model=None):
    p = rates(model, fast=(u.get("speed") == "fast"))
    cc = u.get("cache_creation") or {}
    w5, w1 = cc.get("ephemeral_5m_input_tokens", 0), cc.get("ephemeral_1h_input_tokens", 0)
    if not cc: w5 = U(u, "cache_creation_input_tokens")
    return (U(u,"input_tokens")*p["input"] + U(u,"output_tokens")*p["output"]
            + w5*p["cw5"] + w1*p["cw1"] + cread(u)*p["cr"]) / 1e6

def user_text(o):
    c = o.get("message", {}).get("content")
    if isinstance(c, str): return c
    if isinstance(c, list):
        return " ".join(b.get("text","") for b in c if isinstance(b, dict) and b.get("type")=="text")
    return ""

def is_user_text(o):
    if o.get("type") != "user" or o.get("isSidechain"): return False
    t = user_text(o).strip()
    if not t: return False
    if t.startswith("<command-") or t.startswith("<local-command-"): return False  # /슬래시 명령 래퍼 제외
    return True

_SUB_CACHE = {}

def _scan_subagents(session_id, path):
    """세션의 서브에이전트 transcript에서 (timestamp, usage, model, agentId, message.id) 수집.
    agent-*.jsonl 은 메인 transcript와 별도 파일이라 여기서 직접 읽어야 집계된다."""
    # 실제 배치:
    #   projects/<proj>/<sid>.jsonl                                   메인
    #   projects/<proj>/<sid>/subagents/agent-*.jsonl                 직접 서브에이전트
    #   projects/<proj>/<sid>/subagents/workflows/wf_*/agent-*.jsonl  워크플로 에이전트
    d = os.path.dirname(path) if path else ""
    root = os.path.join(d, session_id or "")
    seen, out = set(), []
    # 메인 transcript와 마찬가지로 한 API 응답이 블록별 레코드로 쪼개져 message.id 를 공유한다.
    # 여기서 한 번만 중복 제거해야 턴 경계를 걸치는 호출이 두 턴에 이중 계상되지 않는다.
    seen_mid = set()
    for pat in (os.path.join(root, "**", "agent-*.jsonl"),
                os.path.join(d, "subagents", "**", "agent-*.jsonl")):   # 구버전 배치 대비
        for f in glob.glob(pat, recursive=True):
            if f in seen: continue
            seen.add(f)
            try:
                lines = open(f).read().splitlines()
            except Exception:
                continue
            for l in lines:
                if not l.strip(): continue
                try: o = json.loads(l)
                except Exception: continue
                if o.get("sessionId") != session_id: continue
                if o.get("type") != "assistant": continue
                m = o.get("message") or {}
                u = m.get("usage")
                if not u: continue
                mid = m.get("id")
                if mid:
                    if mid in seen_mid: continue    # 같은 API 응답의 추가 블록 → 1회만
                    seen_mid.add(mid)
                out.append((o.get("timestamp") or "", u, m.get("model"),
                            o.get("agentId") or "?", mid))
    return out

def subagent_usage(session_id, path):
    key = (session_id, os.path.dirname(path or ""))
    if key not in _SUB_CACHE:
        try: _SUB_CACHE[key] = _scan_subagents(session_id, path)
        except Exception: _SUB_CACHE[key] = []
    return _SUB_CACHE[key]

def recompute_totals(store):
    """turns 리스트에서 누적값을 항상 다시 계산 (증분 누적은 중복/누락에 취약)."""
    t = {"turns": 0, "new": 0, "out": 0, "cr": 0, "cost": 0.0}
    for r in store.get("turns") or []:
        t["turns"] += 1
        t["new"]   += r.get("plan_new", 0)
        t["out"]   += r.get("out", 0)
        t["cr"]    += r.get("cache_read", 0)
        t["cost"]  += r.get("cost", 0)
    store["totals"] = t
    return t

def analyze_turn(recs, start, end=None, save_cum=True, hook=None, path=None):
    turn = recs[start:end]
    # 이 턴의 시각 구간 → 서브에이전트 토큰을 시각으로 이 턴에 귀속시킨다
    ts_lo = recs[start].get("timestamp") or ""
    ts_hi = (recs[end].get("timestamp") or "") if (end is not None and end < len(recs)) else None
    # tool_use_id -> 결과 토큰 추정
    tr = {}
    for o in turn:
        if o.get("type") == "user":
            c = o.get("message", {}).get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        tr[b.get("tool_use_id")] = est_tokens(b.get("content"))
    # 메인 어시스턴트: message.id 로 묶어 usage 중복 제거.
    # (하나의 API 응답이 thinking/text/tool_use 블록별 레코드로 쪼개져 같은 usage를 공유하므로
    #  레코드별 합산은 usage를 블록 수만큼 과다계상함 → message.id 당 usage는 1회만 계상)
    calls = []            # 고유 API 호출 순서대로: {"u": usage, "model": id, "tools": [...]}
    idx_by_id = {}        # message.id -> calls 인덱스
    ag = {"new":0,"out":0,"cr":0,"cost":0.0}; ag_ids = set()
    models = {}           # 정규화 model id -> 호출 수 (한 턴에 모델이 섞일 수 있음)
    for o in turn:
        if o.get("type") != "assistant": continue
        m = o.get("message", {}); u = m.get("usage")
        if not u: continue
        mid = m.get("id") or ("rec:" + str(o.get("uuid")))
        mdl = m.get("model")
        if o.get("isSidechain"):
            if mid not in ag_ids:                       # 사이드체인도 message.id 중복 제거
                ag_ids.add(mid)
                ag["new"]+=new_in(u); ag["out"]+=out(u); ag["cr"]+=cread(u)
                ag["cost"]+=cost(u, mdl)                # 서브에이전트는 자체 모델 단가로
            continue
        if mid not in idx_by_id:
            idx_by_id[mid] = len(calls)
            calls.append({"u": u, "model": mdl, "tools": []})
            if not is_pseudo(mdl):
                k = norm_model(mdl) or (str(mdl) if mdl else "?")
                models[k] = models.get(k, 0) + 1
        for b in (m.get("content") or []):
            if isinstance(b, dict) and b.get("type") == "tool_use":
                inp = b.get("input") or {}
                name = b.get("name","?")
                if name in ("Agent","Task"):  # 서브에이전트: 종류(subagent_type)별로 구분
                    name = f"{name}:{inp.get('subagent_type') or '?'}"
                calls[idx_by_id[mid]]["tools"].append({
                    "name": name,
                    "intake": tr.get(b.get("id"), 0),
                    "gen": est_tokens(inp.get("content") or inp.get("new_string") or "")})

    # 서브에이전트(agent-*.jsonl) 사용량을 시각 구간으로 이 턴에 귀속시킨다.
    # message.id 로 위 사이드체인 집계와 중복 제거 → 양쪽에 다 있어도 1회만 계상.
    agents, amodels = {}, {}
    sid_sub = os.path.basename(path).replace(".jsonl", "") if path else None
    for ts, u, mdl, aid, mid in (subagent_usage(sid_sub, path) if sid_sub else []):
        if ts_lo and ts < ts_lo: continue
        if ts_hi and ts >= ts_hi: continue
        if mid and mid in ag_ids: continue
        if mid: ag_ids.add(mid)
        ag["new"]+=new_in(u); ag["out"]+=out(u); ag["cr"]+=cread(u)
        ag["cost"]+=cost(u, mdl)
        agents[aid] = agents.get(aid, 0) + 1
        if not is_pseudo(mdl):
            k = norm_model(mdl) or (str(mdl) if mdl else "?")
            amodels[k] = amodels.get(k, 0) + 1

    # 메인 호출이 없어도 서브에이전트가 일한 턴은 버리지 않는다.
    # (예전엔 여기서 return None 해서 그 턴의 서브에이전트 토큰이 통째로 누락됐다)
    if not calls and not agents:
        return None

    out_t = sum(out(c["u"]) for c in calls)
    new_t = sum(new_in(c["u"]) for c in calls)
    cr_t  = sum(cread(c["u"]) for c in calls)
    cost_t= sum(cost(c["u"], c.get("model")) for c in calls) + ag["cost"]

    # 도구별 유입(델타법) + 생성(Write/Edit)
    # 도구별 "결과 크기"(문자 기준 추정): 그 도구가 맥락에 넣은 양. 캐시 동작과 무관해 델타법보다 정직함.
    # (주의: 서브에이전트는 내부 토큰이 별도 agent-*.jsonl 에 있어 여기 집계 안 됨. 여기 값은 '반환된 결과'의 크기임)
    intake = defaultdict(int); count = defaultdict(int); gen = defaultdict(int)
    for c in calls:
        for t in c["tools"]:
            count[t["name"]] += 1
            intake[t["name"]] += t["intake"]
            if t["name"] in ("Write","Edit","MultiEdit","NotebookEdit"):
                gen[t["name"]] += t["gen"]

    first_new = new_in(calls[0]["u"]) if calls else 0  # 질문 + 시스템/도구정의(신규분)
    tool_sum  = sum(intake.values())
    loop_refeed = max(0, new_t - first_new - tool_sum)  # 직전 응답 재입력(에이전트 루프)

    # 이 턴 서명(마지막 메인 어시스턴트 uuid) + 로그 레코드(항상 구성 → --rank 재사용)
    sig = ts = None
    for o in reversed(turn):
        if o.get("type") == "assistant" and not o.get("isSidechain"):
            sig, ts = o.get("uuid"), o.get("timestamp"); break
    rec = {"sig": sig, "tsig": recs[start].get("uuid"), "ts": ts,
           "q": user_text(recs[start]).strip().replace("\n"," ")[:200],
           "models": models, "amodels": amodels, "agents": agents,
           "plan_new": new_t+ag["new"]+out_t+ag["out"],
           "cost": round(cost_t, 4),
           "out": out_t+ag["out"], "new_input": new_t+ag["new"], "cache_read": cr_t+ag["cr"],
           "first_new": first_new, "tool_results": tool_sum, "loop_refeed": loop_refeed,
           "tools": {n: {"intake": intake[n], "count": count[n]} for n in intake},
           "gen": dict(gen),
           "agent": {"new": ag["new"], "out": ag["out"], "cr": ag["cr"],
                     "cost": round(ag["cost"], 4), "count": len(agents)}}

    # 세션 로그 파일에 누적(중복 방지). 현재 출력 로직은 그대로 유지.
    cum = {"turns":0,"new":0,"cost":0.0}
    if save_cum:
        sid = (hook or {}).get("session_id") or os.path.basename(path).replace(".jsonl","")
        d = os.path.expanduser("~/.claude/token-usage"); os.makedirs(d, exist_ok=True)
        sp = os.path.join(d, f"{sid}.json")
        store = {"session_id": sid, "totals": {"turns":0,"new":0,"out":0,"cr":0,"cost":0.0},
                 "last_sig": None, "turns": []}
        if os.path.exists(sp):
            try:
                loaded = json.load(open(sp))
                if isinstance(loaded.get("turns"), list): store = loaded   # 신 스키마
            except Exception: pass
        # 턴 시작 uuid(tsig)를 키로 append 대신 replace.
        # 한 턴 안에서 Stop이 여러 번 발생해도(작업 중 사용자 메시지 등) 기록은 항상 1개 →
        # 겹치는 구간이 이중 계상되지 않는다. 누적값은 turns 에서 매번 재계산.
        tsig = rec.get("tsig")
        idx = next((i for i, o in enumerate(store["turns"])
                    if tsig and o.get("tsig") == tsig), None)
        if idx is None:
            store["turns"].append(rec)
        else:
            store["turns"][idx] = rec
        store["last_sig"] = sig; store["session_id"] = sid
        recompute_totals(store)
        try:
            with open(sp, "w") as f:
                json.dump(store, f, ensure_ascii=False)
        except Exception: pass
        cum = store["totals"]

    return dict(q=user_text(recs[start]).strip().replace("\n"," ")[:42],
                out_t=out_t, new_t=new_t, cr_t=cr_t, cost_t=cost_t, ag=ag,
                intake=intake, count=count, gen=gen, rec=rec, models=models,
                amodels=amodels, agents=agents,
                first_new=first_new, loop_refeed=loop_refeed, cum=cum)

def render(r):
    plan = r["new_t"] + r["ag"]["new"] + r["out_t"] + r["ag"]["out"]  # 신규 소비(캐시읽기 제외)
    L = ["", "━━━━━━ 이 턴 플랜 토큰 ━━━━━━", f"Q: {r['q']}"]
    L.append(f"모델: {model_label(r.get('models') or r.get('amodels'))}")
    L.append(f"소진(신규) ~{plan:,}   재사용(캐시) {r['cr_t']+r['ag']['cr']:,}   "
             f"가중≈{fmt_w(r['cost_t'])} (Opus입력 환산)")
    L.append(f"  ├ 출력 생성 {r['out_t']:,}")
    L.append(f"  └ 신규 입력 {r['new_t']:,}")
    L.append(f"       질문+시스템 {r['first_new']:,} / 도구결과 {sum(r['intake'].values()):,} / 루프재입력 {r['loop_refeed']:,}")
    rows = sorted(r["intake"].items(), key=lambda x:-x[1])
    if rows:
        L.append("  도구별 유입(추정):")
        for n, tk in rows:
            L.append(f"    {n:<11} ~{tk:>8,}  ({r['count'][n]}회)")
    for n, tk in sorted(r["gen"].items(), key=lambda x:-x[1]):
        if tk: L.append(f"    {n:<11} 생성 ~{tk:,}")
    if r["ag"]["new"] + r["ag"]["out"] + r["ag"]["cr"]:
        na = len(r.get("agents") or {})
        L.append(f"  에이전트(서브) {na}개: 신규 {r['ag']['new']:,} / 출력 {r['ag']['out']:,}"
                 f" / 캐시 {r['ag']['cr']:,} / 가중≈{fmt_w(r['ag']['cost'])}")
    if INFERRED:
        L.append(f"  ⚠ 계열추정 단가: {', '.join(sorted(INFERRED))}"
                 f"  (정확히 하려면 {PRICE_OVERRIDE} 에 추가)")
    if UNKNOWN:
        L.append(f"  ⚠ 단가 미등록 모델(→{DEFAULT_MODEL} 단가로 계산): {', '.join(sorted(UNKNOWN))}")
    c = r["cum"]
    L.append(f"세션 누적: 소진 ~{c['new']:,}  가중≈{fmt_w(c['cost'])}  ({c['turns']}턴)")
    return "\n".join(L)

def render_log(store):
    turns = store.get("turns", [])
    if not isinstance(turns, list): turns = []   # 구 스키마(flat) 방어
    t = store.get("totals", {})
    L = [f"세션 {store.get('session_id','?')}  |  {t.get('turns',0)}턴  소진~{t.get('new',0):,}  재사용~{t.get('cr',0):,}  가중≈{fmt_w(t.get('cost',0))}",
         "── 가중 사용량 많은 순 ──"]
    for i, r in enumerate(sorted(turns, key=lambda x: -x.get("cost", 0)), 1):
        L.append(f"{i}. 가중≈{fmt_w(r.get('cost',0))}  소진~{r.get('plan_new',0):,}  "
                 f"[{(r.get('ts') or '')[:19]}]  "
                 f"{model_label(r.get('models') or r.get('amodels'))}")
        L.append(f"   Q: {r.get('q','')[:90]}")
        L.append(f"   구성: 질문+시스템 {r.get('first_new',0):,} / 도구결과 {r.get('tool_results',0):,} / 루프재입력 {r.get('loop_refeed',0):,} / 출력 {r.get('out',0):,}")
        top = sorted(r.get("tools", {}).items(), key=lambda x: -x[1].get("intake", 0))[:5]
        if top:
            L.append("   주요 유입: " + ", ".join(f"{n} ~{v.get('intake',0):,}({v.get('count',0)}회)" for n, v in top))
    return "\n".join(L)

def do_log():
    args = [a for a in sys.argv[1:] if a != "--log"]
    d = os.path.expanduser("~/.claude/token-usage")
    sp, note = None, None
    if args:
        a = args[0]
        if os.path.exists(a) and a.endswith(".json"):
            sp = a
        else:
            sid = os.path.basename(a).replace(".jsonl", "").replace(".json", "")
            sp = os.path.join(d, f"{sid}.json")
    else:
        # 세션 미지정: 훅 stdin의 session_id 를 먼저 쓰고, 없으면 최근 수정 파일 + 경고.
        sid = None
        if not sys.stdin.isatty():
            try:
                raw = sys.stdin.read()
                if raw.strip(): sid = (json.loads(raw) or {}).get("session_id")
            except Exception: pass
        if sid:
            sp = os.path.join(d, f"{sid}.json")
        else:
            files = [f for f in glob.glob(os.path.join(d, "*.json"))
                     if os.path.basename(f) != os.path.basename(PRICE_OVERRIDE)]
            sp = max(files, key=os.path.getmtime) if files else None
            if sp:
                note = (f"[plan_usage] 세션 미지정 → 최근 수정 파일 사용: "
                        f"{os.path.basename(sp)[:8]} (동시 세션이면 다른 세션일 수 있음)\n"
                        f"             특정 세션: --log <세션ID>\n")
    if not sp or not os.path.exists(sp):
        print("[plan_usage] 세션 로그 없음"); return
    if note: print(note)
    print(render_log(json.load(open(sp))))

# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────
# 세션 집계는 여기 한 곳만 유지한다. --rank / --rank-all / --repair 가 모두 이걸 쓴다.

def all_transcripts():
    return sorted(p for p in glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"),
                                       recursive=True)
                  if not os.path.basename(p).startswith("agent-"))

def find_transcript(sid):
    sid = os.path.basename(str(sid)).replace(".jsonl", "").replace(".json", "")
    hits = glob.glob(os.path.expanduser(f"~/.claude/projects/**/{sid}.jsonl"), recursive=True)
    return hits[0] if hits else None

def session_totals(path):
    """transcript 1개 -> (store 형태 dict, {모델: 호출수}). 파일에 저장하지 않는다."""
    recs = [json.loads(l) for l in open(path).read().splitlines() if l.strip()]
    starts = [i for i, o in enumerate(recs) if is_user_text(o)]
    store = {"session_id": os.path.basename(path).replace(".jsonl", ""),
             "totals": {"turns":0,"new":0,"out":0,"cr":0,"cost":0.0},
             "last_sig": None, "turns": []}
    models = {}
    for idx, s in enumerate(starts):
        e = starts[idx+1] if idx+1 < len(starts) else len(recs)
        r = analyze_turn(recs, s, e, save_cum=False, hook=None, path=path)
        if not r: continue
        rec = r["rec"]; store["turns"].append(rec)
        # 세션 개요용이므로 메인 + 서브에이전트 모델을 함께 집계
        for src in ("models", "amodels"):
            for k, v in (rec.get(src) or {}).items():
                models[k] = models.get(k, 0) + v
    recompute_totals(store)
    if store["turns"]:
        store["last_sig"] = store["turns"][-1].get("sig")   # 훅이 마지막 턴을 또 추가하지 않도록
    return store, models

def stored_totals():
    """저장된 세션 로그의 누적값 {sid: totals} (prices.json 제외)."""
    out, d = {}, os.path.expanduser("~/.claude/token-usage")
    for f in glob.glob(os.path.join(d, "*.json")):
        if os.path.basename(f) == os.path.basename(PRICE_OVERRIDE): continue
        if f.endswith(".bak"): continue
        try:
            j = json.load(open(f))
            sid = j.get("session_id") or os.path.basename(f)[:-5]
            if isinstance(j.get("totals"), dict): out[sid] = j["totals"]
        except Exception: pass
    return out

def arg_value(flag, default=None):
    """--flag VALUE / --flag=VALUE 에서 값 추출."""
    av = sys.argv[1:]
    for i, a in enumerate(av):
        if a == flag and i+1 < len(av): return av[i+1]
        if a.startswith(flag + "="): return a.split("=", 1)[1]
    return default

def file_day(path):
    return datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()

# ── 서브커맨드 ───────────────────────────────────────────────────────────────

def do_rank():
    # 로그 파일 없이 transcript에서 즉석으로 전체 턴 랭킹(설치 전 세션·동시 세션 대응)
    args = [a for a in sys.argv[1:] if a != "--rank"]
    path = None
    if args:
        a = args[0]
        path = a if os.path.exists(a) else find_transcript(a)
    if not path:
        files = all_transcripts()
        path = max(files, key=os.path.getmtime) if files else None
    if not path or not os.path.exists(path):
        print("[plan_usage] transcript 없음"); return
    store, _ = session_totals(path)
    print(render_log(store))

def do_rank_all():
    """모든 transcript를 재계산해 세션별 표로 출력. --since YYYY-MM-DD / --json 지원."""
    since, as_json = arg_value("--since"), "--json" in sys.argv
    stored, rows, skipped = stored_totals(), [], 0
    for path in all_transcripts():
        day = file_day(path)
        if since and day < since: continue
        try:
            store, models = session_totals(path)
        except Exception:
            skipped += 1; continue
        t = store["totals"]
        if not t["turns"]:
            skipped += 1; continue
        sid = store["session_id"]
        rows.append({"session_id": sid, "date": day, "totals": t, "models": models,
                     "stored_cost": (stored.get(sid) or {}).get("cost"),
                     "top_turn": max(store["turns"], key=lambda r: r.get("cost", 0))})
    rows.sort(key=lambda r: -r["totals"]["cost"])

    if as_json:
        print(json.dumps({"sessions": rows, "skipped": skipped,
                          "inferred": sorted(INFERRED), "unknown": sorted(UNKNOWN)},
                         ensure_ascii=False, indent=2))
        return

    L = [f"세션 {len(rows)}개 집계" + (f" (제외 {skipped}개)" if skipped else "")
         + (f"  since={since}" if since else ""), "",
         f"{'날짜':<11}{'세션':<10}{'턴':>4}{'소진':>14}{'캐시읽기':>16}"
         f"{'가중(재)':>10}{'가중(기존)':>10}{'배율':>7}  모델", "─" * 112]
    s_turns = s_new = s_cr = 0; s_cost = s_old = 0.0; matched = 0; m_new = 0.0
    for r in rows:
        t, old = r["totals"], r["stored_cost"]
        olds  = f"{fmt_w(old):>10}" if old else "         —"
        ratio = f"{t['cost']/old:.2f}x" if old else "—"
        mlab = model_label({k.replace("claude-", ""): v for k, v in r["models"].items()})
        L.append(f"{r['date']:<11}{r['session_id'][:8]:<10}{t['turns']:>4}{t['new']:>14,}"
                 f"{t['cr']:>16,}{fmt_w(t['cost']):>10}{olds}{ratio:>7}  {mlab[:34]}")
        s_turns += t["turns"]; s_new += t["new"]; s_cr += t["cr"]; s_cost += t["cost"]
        if old: s_old += old; m_new += t["cost"]; matched += 1
    L += ["─" * 112,
          f"{'합계':<19}{s_turns:>4}{s_new:>14,}{s_cr:>16,}{fmt_w(s_cost):>10}"]
    if matched:
        L.append(f"\n저장 로그가 있는 {matched}개 세션만 비교: "
                 f"기존 가중≈{fmt_w(s_old)} → 재계산 가중≈{fmt_w(m_new)}")

    agg = {}
    for r in rows:
        for k, v in r["models"].items(): agg[k] = agg.get(k, 0) + v
    if agg:
        L.append("\n=== 모델별 API 호출 수 (가중치: 입력/출력, Opus입력=1.0 기준) ===")
        for k, v in sorted(agg.items(), key=lambda x: -x[1]):
            p = rates(k)
            L.append(f"  {k:<24}{v:>6}회   x{p['input']/OPUS_UNIT:g} / x{p['output']/OPUS_UNIT:g}")

    tops = sorted((r["top_turn"] for r in rows), key=lambda x: -x.get("cost", 0))[:5]
    if tops:
        L.append("\n=== 가중 사용량 최다 턴 Top 5 ===")
        for i, tp in enumerate(tops, 1):
            L.append(f"{i}. 가중≈{fmt_w(tp.get('cost',0))}  소진~{tp.get('plan_new',0):,}  "
                     f"[{(tp.get('ts') or '')[:19]}]  {model_label(tp.get('models'))}")
            L.append(f"   Q: {tp.get('q','')[:80]}")
            L.append(f"   질문+시스템 {tp.get('first_new',0):,} / 도구결과 {tp.get('tool_results',0):,}"
                     f" / 루프재입력 {tp.get('loop_refeed',0):,} / 출력 {tp.get('out',0):,}")
    if INFERRED: L.append(f"\n⚠ 계열추정 단가: {', '.join(sorted(INFERRED))}")
    if UNKNOWN:  L.append(f"⚠ 단가 미등록: {', '.join(sorted(UNKNOWN))}")
    print("\n".join(L))

def do_repair():
    """저장된 세션 누적값을 transcript 재계산값으로 덮어쓴다. --yes 없으면 미리보기만."""
    apply_ = "--yes" in sys.argv
    d = os.path.expanduser("~/.claude/token-usage")
    stored = stored_totals()
    if not stored:
        print("[plan_usage] 저장된 세션 로그 없음"); return
    print(f"{'세션':<10}{'턴 기존→새':>16}{'가중 기존→새':>26}   비고")
    print("─" * 72)
    done = 0
    for sid in sorted(stored, key=lambda s: -(stored[s].get("cost") or 0)):
        old, path = stored[sid], find_transcript(sid)
        if not path:
            print(f"{sid[:8]:<10}{'—':>16}{'—':>26}   건너뜀: transcript 없음"); continue
        try:
            store, _ = session_totals(path)
        except Exception as e:
            print(f"{sid[:8]:<10}{'—':>16}{'—':>26}   건너뜀: {type(e).__name__}"); continue
        t = store["totals"]
        line = (f"{sid[:8]:<10}{old.get('turns',0):>7}→{t['turns']:<8}"
                f"{fmt_w(old.get('cost',0)):>12}→{fmt_w(t['cost']):<13}")
        if not apply_:
            print(line + "   (미리보기)"); continue
        sp = os.path.join(d, f"{sid}.json")
        try:
            if os.path.exists(sp) and not os.path.exists(sp + ".bak"):
                shutil.copy2(sp, sp + ".bak")          # 최초 1회만 백업
            store["session_id"] = sid
            with open(sp, "w") as f:
                json.dump(store, f, ensure_ascii=False)
            print(line + "   덮어씀"); done += 1
        except Exception as e:
            print(line + f"   실패: {type(e).__name__}")
    print("─" * 72)
    if apply_:
        print(f"{done}개 세션 갱신 완료. 원본은 *.json.bak 로 보관됨.")
    else:
        print("실제로 덮어쓰려면 --yes 를 붙이세요:")
        print("  python3 ~/.claude/hooks/plan_usage.py --repair --yes")

def main():
    if "--log" in sys.argv:
        return do_log()
    if "--rank-all" in sys.argv:      # --rank 보다 먼저 검사
        return do_rank_all()
    if "--repair" in sys.argv:
        return do_repair()
    if "--rank" in sys.argv:
        return do_rank()
    path, hook = get_source()
    if not path or not os.path.exists(path):
        print("[plan_usage] transcript not found"); return
    recs = [json.loads(l) for l in open(path).read().splitlines() if l.strip()]
    if "--all" in sys.argv:
        starts = [i for i,o in enumerate(recs) if is_user_text(o)]
        for idx, s in enumerate(starts):
            e = starts[idx+1] if idx+1 < len(starts) else len(recs)
            r = analyze_turn(recs, s, e, save_cum=False, hook=hook, path=path)
            if r: print(render(r))
        return
    start = next((i for i in range(len(recs)-1,-1,-1) if is_user_text(recs[i])), None)
    if start is None: return
    r = analyze_turn(recs, start, None, save_cum=True, hook=hook, path=path)
    if not r: return
    report = render(r)
    print(json.dumps({"systemMessage": report}) if hook else report)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 전역 Stop 훅: 어떤 오류가 나도 세션을 방해하지 않고 조용히 종료
