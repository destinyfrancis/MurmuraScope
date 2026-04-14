# MurmuraScope 升級計劃 — 從分析到商用就緒

**版本：** 1.0
**日期：** 2026-04-13
**目標：** 將 MurmuraScope 從技術原型提升至 Tier 1 商用 MVP（4–6 週），並為 Tier 2 發佈級鋪路
**前提：** 本計劃基於 4 維度系統分析（實體抽取、人格引擎、模擬穩定性、安全生產就緒度）及 MiroFish 競品對比

---

## 目錄

- [Phase 0：安全修復（第 1–2 週）](#phase-0安全修復第-12-週)
- [Phase 1：穩定性 & 降級機制（第 2–3 週）](#phase-1穩定性--降級機制第-23-週)
- [Phase 2：人格動態化 & 關係增強（第 3–5 週）](#phase-2人格動態化--關係增強第-35-週)
- [Phase 3：虛構世界支援（第 4–5 週）](#phase-3虛構世界支援第-45-週)
- [Phase 4：DX & 產品打磨（第 5–6 週）](#phase-4dx--產品打磨第-56-週)
- [Phase 5：測試覆蓋 & 驗證（貫穿全程）](#phase-5測試覆蓋--驗證貫穿全程)
- [附錄 A：文件清單速查](#附錄-a文件清單速查)
- [附錄 B：驗收標準](#附錄-b驗收標準)

---

## Phase 0：安全修復（第 1–2 週）

**優先級：CRITICAL — 必須在任何其他工作之前完成**

### 0.1 Admin 端點加認證

**問題：** `/simulation/admin/*` 共 7 個端點完全無認證，任何人可觸發昂貴基準測試或讀取系統配置。

**文件：** `backend/app/api/simulation.py`（第 519–836 行）

**修改方案：**

```python
# 在 simulation.py 頂部已有 import：
# from backend.app.api.auth import UserProfile, get_optional_user

# 新增 admin 角色檢查依賴
from backend.app.api.auth import get_current_user

async def require_admin(user: UserProfile = Depends(get_current_user)) -> UserProfile:
    """Reject non-admin users with 403."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
```

**逐一修改以下端點（共 7 個）：**

| 行號 | 端點 | 修改 |
|------|------|------|
| 519 | `GET /admin/benchmarks` | 加 `user: UserProfile = Depends(require_admin)` 參數 |
| 548 | `GET /admin/benchmarks/{target}` | 同上 |
| 584 | `POST /admin/benchmarks/run` | 同上 |
| 669 | `POST /admin/profile` | 同上 |
| 741 | `GET /admin/profile-results` | 同上 |
| 794 | `GET /admin/shards` | 同上 |
| 836 | `POST /admin/shards/rebalance` | 同上 |

**前置條件：** `users` 表需新增 `is_admin BOOLEAN DEFAULT 0` 欄位。

```sql
-- backend/database/schema.sql 中 users 表新增
ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0;
```

**同時修改 `auth.py` 的 `UserProfile` model：**

```python
# backend/app/api/auth.py — UserProfile class
class UserProfile(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str
    email: str
    is_admin: bool = False  # 新增
```

並喺 `get_current_user()` 中從 DB 讀取 `is_admin`。

**測試：** 至少 7 個測試 — 每個 admin 端點各 1 個，驗證無 token 返回 401、非 admin 返回 403、admin 返回 200。

---

### 0.2 WebSocket 認證改為必須

**問題：** `backend/app/api/ws.py` 第 74–78 行，`token` 參數有預設空字串，無 token 亦可連接。

**文件：** `backend/app/api/ws.py`

**修改方案：**

```python
# 修改前（第 74-78 行）：
@router.websocket("/progress/{session_id}")
async def simulation_progress(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(default=""),
) -> None:

# 修改後：
@router.websocket("/progress/{session_id}")
async def simulation_progress(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(...),  # 改為必填
) -> None:
```

然後喺函數體內（連接接受之前），驗證 token：

```python
    # 在 await websocket.accept() 之前加入：
    if not token:
        await websocket.close(code=4001, reason="Token required")
        return

    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4003, reason="Invalid token")
            return
    except JWTError:
        await websocket.close(code=4003, reason="Invalid token")
        return
```

**注意：** 需要從 `auth.py` import `_SECRET_KEY` 和 `_ALGORITHM`，或者抽出一個共用嘅 `validate_token(token: str) -> str | None` 函數。

**測試：** 2 個測試 — 無 token 被拒（4001）、無效 token 被拒（4003）。

---

### 0.3 Workspace 所有權驗證

**問題：** 知道 session_id 和 workspace_id 就可以將任何 session 加入任何 workspace，無所有權檢查。

**文件：** `backend/app/api/workspace.py`

**修改方案：** 在 `POST /workspace/{id}/sessions/{session_id}` 端點加入：

```python
# 1. 驗證 workspace 歸屬當前用戶
async with get_db() as db:
    ws_row = await (await db.execute(
        "SELECT owner_id FROM workspaces WHERE id = ?", (workspace_id,)
    )).fetchone()
    if not ws_row:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # 檢查用戶是 owner 或 member
    member = await (await db.execute(
        "SELECT 1 FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
        (workspace_id, user.user_id),
    )).fetchone()
    if ws_row["owner_id"] != user.user_id and not member:
        raise HTTPException(status_code=403, detail="Not a workspace member")

    # 2. 驗證 session 歸屬當前用戶
    sess_row = await (await db.execute(
        "SELECT user_id FROM simulation_sessions WHERE id = ?", (session_id,)
    )).fetchone()
    if not sess_row or sess_row["user_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Session not owned by user")
```

**測試：** 3 個測試 — 非 member 添加 session 返回 403、非 owner session 返回 403、正常添加返回 200。

---

### 0.4 成本追蹤持久化

**問題：** `backend/app/services/cost_tracker.py` 用記憶體字典 `_session_costs`，伺服器重啟後所有成本數據丟失，硬上限可被繞過。

**文件：** `backend/app/services/cost_tracker.py`

**修改方案：**

Step 1 — Schema 新增表：

```sql
-- backend/database/schema.sql
CREATE TABLE IF NOT EXISTS session_costs (
    session_id TEXT PRIMARY KEY,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    is_paused BOOLEAN NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Step 2 — 修改 `record_cost()` 同時寫入 DB：

```python
async def record_cost(session_id: str, cost_usd: float) -> None:
    if not session_id:
        return

    async with _cost_lock:
        prev = _session_costs.get(session_id, 0.0)
        total = prev + cost_usd
        _session_costs[session_id] = total

    # 持久化到 DB（best-effort，不阻塞主流程）
    try:
        async with get_db() as db:
            await db.execute(
                """INSERT INTO session_costs (session_id, total_cost_usd, updated_at)
                   VALUES (?, ?, datetime('now'))
                   ON CONFLICT(session_id) DO UPDATE SET
                     total_cost_usd = ?,
                     updated_at = datetime('now')""",
                (session_id, total, total),
            )
            await db.commit()
    except Exception:
        logger.warning("Failed to persist cost for session %s", session_id)

    # ... 保留原有 budget/hard_cap 邏輯
```

Step 3 — 啟動時從 DB 恢復：

```python
async def restore_costs_from_db() -> None:
    """Called at app startup to reload persisted cost state."""
    try:
        async with get_db() as db:
            rows = await (await db.execute(
                "SELECT session_id, total_cost_usd, is_paused FROM session_costs"
            )).fetchall()
        for row in rows or []:
            _session_costs[row["session_id"]] = row["total_cost_usd"]
            if row["is_paused"]:
                _session_paused[row["session_id"]] = True
    except Exception:
        logger.warning("Failed to restore costs from DB")
```

在 `backend/app/__init__.py` 的 `lifespan()` 中調用 `await restore_costs_from_db()`。

**測試：** 3 個測試 — 記錄成本後 DB 有值、重啟後恢復正確、硬上限後 is_paused 寫入 DB。

---

### 0.5 昂貴端點加速率限制

**問題：** `POST /simulation/create` 無速率限制，可被濫用觸發大量 LLM 調用。

**文件：** `backend/app/api/simulation.py`

**修改方案：**

```python
# 找到 POST /simulation/create 端點定義，加入 @_limiter.limit()

@router.post("/create", response_model=APIResponse)
@_limiter.limit("10/minute")  # 新增：每用戶每分鐘最多 10 次創建
async def create_simulation(
    request: Request,  # slowapi 需要 Request 參數
    body: SimulationCreateRequest,
    user: UserProfile | None = Depends(get_optional_user),
) -> APIResponse:
```

同樣對以下端點加限制：

| 端點 | 限制 |
|------|------|
| `POST /simulation/create` | 10/minute |
| `POST /simulation/start` | 5/minute |
| `POST /simulation/{id}/shock` | 10/minute |
| `POST /admin/benchmarks/run` | 2/minute |
| `POST /admin/profile` | 2/minute |

**測試：** 1 個測試 — 超過速率限制返回 429。

---

### 0.6 `limit` 參數上限驗證

**問題：** 多個 list 端點接受無上限 `limit` 值，可拉取整個數據庫。

**文件：** `backend/app/api/simulation.py`（及其他 list 端點）

**修改方案 — 通用守衛函數：**

```python
# backend/app/utils/pagination.py（新文件）

def clamp_limit(limit: int, max_limit: int = 100) -> int:
    """Clamp a user-supplied limit to [1, max_limit]."""
    return max(1, min(limit, max_limit))
```

在所有接受 `limit` 參數嘅端點使用：

```python
from backend.app.utils.pagination import clamp_limit

@router.get("/list-sessions")
async def list_sessions(limit: int = 50):
    limit = clamp_limit(limit, max_limit=200)
    # ...
```

**受影響端點：** `list_sessions`、`list_benchmarks`、`GET /workspace/{id}/sessions` 等。

**測試：** 1 個測試 — limit=99999 被 clamp 到 200。

---

## Phase 1：穩定性 & 降級機制（第 2–3 週）

### 1.1 LLM 全面故障自動降級到 Lite 模式

**問題：** 當 LLM provider（OpenRouter）宕機或配額耗盡時，所有 agent 決策靜默跳過，模擬繼續但產出零增量。無自動切換到 `lite_hooks.py` 嘅規則模式。

**文件：** `backend/app/services/simulation_hooks_kg_driven.py`

**修改方案：**

Step 1 — 在 `KGSessionState` 加追蹤字段：

```python
# backend/app/models/kg_session_state.py
@dataclass
class KGSessionState:
    # ... 現有字段 ...
    consecutive_llm_failures: int = 0       # 新增
    auto_degraded_to_lite: bool = False      # 新增
```

Step 2 — 在 `_deliberate_for_round()` 中追蹤連續失敗：

```python
# simulation_hooks_kg_driven.py 中的 _deliberate_for_round 方法
# 在收集所有 agent 決策結果之後，統計成功/失敗：

successful = sum(1 for r in results if not isinstance(r, Exception))
failed = sum(1 for r in results if isinstance(r, Exception))
total = successful + failed

if total > 0 and failed / total > 0.8:
    kg_state.consecutive_llm_failures += 1
    logger.warning(
        "Round %d: %.0f%% LLM failures (%d/%d). Consecutive: %d",
        round_number, (failed / total) * 100, failed, total,
        kg_state.consecutive_llm_failures,
    )
else:
    kg_state.consecutive_llm_failures = 0  # 重置

# 連續 2 輪 80%+ 失敗 → 自動降級
_AUTO_DEGRADE_THRESHOLD = 2
if (
    kg_state.consecutive_llm_failures >= _AUTO_DEGRADE_THRESHOLD
    and not kg_state.auto_degraded_to_lite
):
    kg_state.lite_ensemble = True
    kg_state.auto_degraded_to_lite = True
    logger.warning(
        "Session %s: Auto-degraded to lite mode after %d consecutive LLM failure rounds",
        session_id,
        kg_state.consecutive_llm_failures,
    )
    # 推送 WebSocket 通知
    await push_progress(session_id, {
        "type": "warning",
        "message": "LLM provider unavailable. Switched to rule-based simulation mode.",
    })
```

Step 3 — 加 LLM 恢復檢測（可選）：

```python
# 每 5 輪嘗試一次 LLM ping
if kg_state.auto_degraded_to_lite and round_number % 5 == 0:
    try:
        test_resp = await llm_client.chat([{"role": "user", "content": "ping"}])
        if test_resp and test_resp.content:
            kg_state.lite_ensemble = False
            kg_state.auto_degraded_to_lite = False
            kg_state.consecutive_llm_failures = 0
            logger.info("Session %s: LLM recovered, switching back to full mode", session_id)
    except Exception:
        pass  # 仍然降級
```

**測試：** 3 個測試 — 連續 2 輪失敗觸發降級、降級後使用 lite hooks、LLM 恢復後切回。

---

### 1.2 斷路器模式

**問題：** OpenRouter 配額耗盡時，每個 agent 嘅 3 次重試全失敗，300 個 agent × 3 次 = 900 次無效 API 調用。

**文件：** `backend/app/utils/llm_client.py`

**修改方案 — 新建 `backend/app/utils/circuit_breaker.py`：**

```python
"""Simple circuit breaker for LLM API calls."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

@dataclass
class CircuitBreaker:
    """Three-state circuit breaker: CLOSED → OPEN → HALF_OPEN."""

    failure_threshold: int = 10      # 連續失敗 N 次後斷開
    recovery_timeout_s: float = 60.0  # 斷開後等待 N 秒嘗試恢復
    half_open_max_calls: int = 3      # HALF_OPEN 最多試 N 次

    _state: str = field(default="CLOSED", init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def can_proceed(self) -> bool:
        async with self._lock:
            if self._state == "CLOSED":
                return True
            if self._state == "OPEN":
                if time.monotonic() - self._last_failure_time >= self.recovery_timeout_s:
                    self._state = "HALF_OPEN"
                    self._half_open_calls = 0
                    return True
                return False
            # HALF_OPEN
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

    async def record_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            self._state = "CLOSED"

    async def record_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state = "OPEN"
                self._last_failure_time = time.monotonic()

    @property
    def is_open(self) -> bool:
        return self._state == "OPEN"
```

在 `llm_client.py` 中使用：

```python
# backend/app/utils/llm_client.py 頂部
from backend.app.utils.circuit_breaker import CircuitBreaker

_circuit_breaker = CircuitBreaker(failure_threshold=10, recovery_timeout_s=60.0)

# 在 chat() 方法中：
async def chat(self, messages: list[dict], ...) -> LLMResponse:
    if not await _circuit_breaker.can_proceed():
        raise CircuitBreakerOpenError("LLM circuit breaker is open — too many consecutive failures")

    try:
        response = await self._call_provider(messages, ...)
        await _circuit_breaker.record_success()
        return response
    except Exception as exc:
        await _circuit_breaker.record_failure()
        raise
```

新增 exception：

```python
class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open."""
```

**測試：** 4 個測試 — 正常通過、達閾值斷開、超時後 HALF_OPEN、成功恢復 CLOSED。

---

### 1.3 每輪超時預算

**問題：** 無每輪總超時上限，LLM-heavy 輪次可能阻塞無限期。

**文件：** `backend/app/services/simulation_runner.py`

**修改方案：** 在 `_execute_round_hooks()` 中加入整輪超時：

```python
_MAX_ROUND_DURATION_S = 180.0  # 3 分鐘上限

async def _execute_round_hooks(self, session_id: str, round_number: int, ...) -> None:
    try:
        await asyncio.wait_for(
            self._execute_round_hooks_inner(session_id, round_number, ...),
            timeout=_MAX_ROUND_DURATION_S,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Round %d for session %s exceeded %ds timeout — skipping remainder",
            round_number, session_id, _MAX_ROUND_DURATION_S,
        )
        await push_progress(session_id, {
            "type": "warning",
            "message": f"Round {round_number} timed out after {_MAX_ROUND_DURATION_S}s",
        })
```

**測試：** 1 個測試 — mock slow hook，驗證超時後模擬繼續。

---

## Phase 2：人格動態化 & 關係增強（第 3–5 週）

### 2.1 人格演化引擎

**問題：** Big Five 特質初始化後靜態不變。Harry 嘅神經質應隨著模擬推進逐漸下降（成長弧線）。

**文件：** 新建 `backend/app/services/personality_evolution.py`

**設計：**

```python
"""Personality Evolution Engine.

Adjusts Big Five traits every N rounds based on accumulated experiences.
Changes are incremental (±0.02 max per adjustment) to prevent sudden personality flips.

Rules:
  - Consistent positive interactions → neuroticism decreases
  - Repeated leadership actions → extraversion increases
  - Exposure to diverse viewpoints → openness increases
  - Betrayal / trust violation → agreeableness decreases
  - Achievement of goals → conscientiousness reinforced
"""

from __future__ import annotations

from dataclasses import dataclass

_EVOLUTION_INTERVAL = 5  # 每 5 輪調整一次
_MAX_DELTA_PER_ADJUSTMENT = 0.02  # 每次最大變化 ±0.02
_TRAIT_FLOOR = 0.05
_TRAIT_CEILING = 0.95


@dataclass(frozen=True)
class PersonalityDelta:
    """Immutable record of a personality adjustment."""
    agent_id: int
    round_number: int
    openness_delta: float = 0.0
    conscientiousness_delta: float = 0.0
    extraversion_delta: float = 0.0
    agreeableness_delta: float = 0.0
    neuroticism_delta: float = 0.0
    reason: str = ""


async def compute_personality_evolution(
    session_id: str,
    agent_id: int,
    round_number: int,
    recent_actions: list[dict],
    recent_interactions: list[dict],
    belief_changes: dict[str, float],
    current_traits: dict[str, float],
) -> PersonalityDelta | None:
    """Compute incremental Big Five adjustments.

    Returns None if round_number is not an evolution interval or
    if accumulated experience is insufficient to justify change.
    """
    if round_number % _EVOLUTION_INTERVAL != 0:
        return None

    deltas = {
        "openness_delta": 0.0,
        "conscientiousness_delta": 0.0,
        "extraversion_delta": 0.0,
        "agreeableness_delta": 0.0,
        "neuroticism_delta": 0.0,
    }
    reasons: list[str] = []

    # Rule 1: Positive interaction ratio → neuroticism down
    if recent_interactions:
        positive_ratio = sum(
            1 for i in recent_interactions if i.get("valence", 0) > 0
        ) / len(recent_interactions)
        if positive_ratio > 0.7:
            deltas["neuroticism_delta"] = -_MAX_DELTA_PER_ADJUSTMENT
            reasons.append(f"high positive interaction ratio ({positive_ratio:.0%})")

    # Rule 2: Leadership actions → extraversion up
    leadership_actions = sum(
        1 for a in recent_actions if a.get("action_type") in ("lead", "organize", "propose")
    )
    if leadership_actions >= 2:
        deltas["extraversion_delta"] = _MAX_DELTA_PER_ADJUSTMENT
        reasons.append(f"{leadership_actions} leadership actions")

    # Rule 3: Belief diversity exposure → openness up
    belief_magnitude = sum(abs(v) for v in belief_changes.values())
    if belief_magnitude > 0.3:
        deltas["openness_delta"] = _MAX_DELTA_PER_ADJUSTMENT * 0.5
        reasons.append(f"belief shift magnitude {belief_magnitude:.2f}")

    # Rule 4: Trust violations → agreeableness down
    betrayals = sum(
        1 for i in recent_interactions if i.get("valence", 0) < -0.5
    )
    if betrayals >= 2:
        deltas["agreeableness_delta"] = -_MAX_DELTA_PER_ADJUSTMENT
        reasons.append(f"{betrayals} negative interactions")

    # Clamp all deltas
    for key in deltas:
        trait_name = key.replace("_delta", "")
        current = current_traits.get(trait_name, 0.5)
        new_val = current + deltas[key]
        if new_val < _TRAIT_FLOOR:
            deltas[key] = _TRAIT_FLOOR - current
        elif new_val > _TRAIT_CEILING:
            deltas[key] = _TRAIT_CEILING - current

    if all(abs(v) < 0.001 for v in deltas.values()):
        return None

    return PersonalityDelta(
        agent_id=agent_id,
        round_number=round_number,
        reason="; ".join(reasons),
        **deltas,
    )
```

**整合點：** 在 `simulation_hooks_kg_driven.py` 的 Group 3 hooks 中呼叫（每 5 輪一次），更新 DB 中 `agent_profiles` 的 Big Five 欄位。

**Schema 新增：**

```sql
CREATE TABLE IF NOT EXISTS personality_evolution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    openness_delta REAL,
    conscientiousness_delta REAL,
    extraversion_delta REAL,
    agreeableness_delta REAL,
    neuroticism_delta REAL,
    reason TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

**測試：** 5 個測試 — 每條規則各 1 個 + clamp 邊界 + 非進化輪返回 None。

---

### 2.2 不對稱關係存儲

**問題：** RelationshipEngine 每對 agent 只存一個 `RelationshipState`，更新時兩方感受相同。Dumbledore 操縱 Harry 但 Harry 信任 Dumbledore — 系統無法表達。

**文件：** `backend/app/models/relationship_state.py`、`backend/app/services/relationship_engine.py`

**修改方案：**

Step 1 — 在 `RelationshipState` 加 directional 字段：

```python
# backend/app/models/relationship_state.py

@dataclass(frozen=True)
class RelationshipState:
    agent_a_id: int
    agent_b_id: int
    # ... 現有字段（intimacy, passion, commitment, trust）...

    # 新增：B 方視角嘅 trust（A→B 和 B→A 可能不同）
    trust_b_perspective: float = 0.5  # B 對 A 的信任
    # 原有 trust 字段 = A 對 B 的信任

    # 新增：deception intent（0=完全誠實, 1=完全欺騙）
    deception_a_to_b: float = 0.0  # A 對 B 的欺騙意圖
    deception_b_to_a: float = 0.0  # B 對 A 的欺騙意圖
```

Step 2 — 修改 `update_from_interaction()` 支援非對稱更新：

```python
# backend/app/services/relationship_engine.py

def update_from_interaction(
    state: RelationshipState,
    interaction_valence: float,
    *,
    perspective: str = "both",  # "a_to_b" | "b_to_a" | "both"
    deception_delta: float = 0.0,
) -> RelationshipState:
    """Update relationship from an interaction, optionally asymmetric."""

    # 現有邏輯計算 new_trust, new_intimacy 等...

    if perspective == "a_to_b":
        return replace(state, trust=new_trust, intimacy=new_intimacy, ...)
    elif perspective == "b_to_a":
        return replace(state, trust_b_perspective=new_trust, ...)
    else:
        return replace(
            state,
            trust=new_trust,
            trust_b_perspective=new_trust,  # 對稱更新（向後兼容）
            intimacy=new_intimacy,
            ...
        )
```

Step 3 — Schema：

```sql
-- agent_relationships 表新增欄位
ALTER TABLE agent_relationships ADD COLUMN trust_b_perspective REAL DEFAULT 0.5;
ALTER TABLE agent_relationships ADD COLUMN deception_a_to_b REAL DEFAULT 0.0;
ALTER TABLE agent_relationships ADD COLUMN deception_b_to_a REAL DEFAULT 0.0;
```

**向後兼容：** 預設 `perspective="both"` 保持現有行為不變。

**測試：** 4 個測試 — 對稱更新（向後兼容）、A→B 單向更新、B→A 單向更新、deception 字段持久化。

---

### 2.3 信念主題模板系統

**問題：** 信念系統為 HK 場景設計嘅 6 個固定主題不適用虛構世界。

**文件：** 新建 `backend/app/services/belief_topic_generator.py`

**設計：**

```python
"""Generate scenario-relevant belief topics via LLM.

Called during Step 2 (Environment Setup) to define 6–10 belief axes
specific to the seed text. For Harry Potter, this might produce:
  dark_arts_threat, authority_trust, blood_purity_acceptance,
  friendship_loyalty, house_identity, muggle_integration
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger

logger = get_logger(__name__)

_TOPIC_GENERATION_PROMPT = """\
Given the following scenario description, generate 6-10 belief topics
that agents in this scenario would hold opinions about.

Each topic should be:
1. A measurable opinion axis (0.0 = strongly disagree, 1.0 = strongly agree)
2. Relevant to the scenario's core conflicts
3. Named in snake_case (English)
4. Include a short description and what 0.0 vs 1.0 means

Scenario: {scenario_description}

Return JSON array:
[
  {{
    "id": "topic_snake_case",
    "label": "Human-readable label",
    "description": "What this belief measures",
    "low_label": "What 0.0 means",
    "high_label": "What 1.0 means"
  }}
]
"""


@dataclass(frozen=True)
class BeliefTopic:
    id: str
    label: str
    description: str
    low_label: str
    high_label: str


async def generate_belief_topics(
    scenario_description: str,
    llm_client: LLMClient,
) -> list[BeliefTopic]:
    """Generate scenario-specific belief topics via LLM."""

    prompt = _TOPIC_GENERATION_PROMPT.format(
        scenario_description=scenario_description[:3000],
    )
    result = await llm_client.chat_json([
        {"role": "system", "content": "Return valid JSON only."},
        {"role": "user", "content": prompt},
    ])
    if not result or not isinstance(result, list):
        logger.warning("Failed to generate belief topics, using defaults")
        return _default_topics()

    topics = []
    for item in result[:10]:
        topics.append(BeliefTopic(
            id=item.get("id", f"topic_{len(topics)}"),
            label=item.get("label", "Unknown"),
            description=item.get("description", ""),
            low_label=item.get("low_label", "Disagree"),
            high_label=item.get("high_label", "Agree"),
        ))
    return topics or _default_topics()


def _default_topics() -> list[BeliefTopic]:
    """Fallback topics when LLM generation fails."""
    return [
        BeliefTopic("authority_trust", "Authority Trust", "Trust in authority figures", "Distrust", "Full trust"),
        BeliefTopic("cooperation", "Cooperation", "Willingness to cooperate", "Defect", "Cooperate"),
        BeliefTopic("risk_tolerance", "Risk Tolerance", "Appetite for risk", "Risk-averse", "Risk-seeking"),
        BeliefTopic("tradition", "Tradition", "Value of tradition vs change", "Progressive", "Traditional"),
        BeliefTopic("group_loyalty", "Group Loyalty", "In-group loyalty strength", "Individualist", "Collectivist"),
        BeliefTopic("optimism", "Optimism", "Outlook on future", "Pessimistic", "Optimistic"),
    ]
```

**整合：** 在 `ScenarioGenerator` 的 `generate()` 中呼叫，將生成嘅 topics 存入 `UniversalScenarioConfig`，並在 `belief_system.py` 初始化時使用。

**測試：** 3 個測試 — LLM 正常生成、LLM 失敗用 default、上限 10 個主題。

---

## Phase 3：虛構世界支援（第 4–5 週）

### 3.1 時間活化參數化

**問題：** `temporal_activation.py` 硬編碼 HK 黃金時段（18:00–23:00）及 08:00 起始小時。

**文件：** `backend/app/services/temporal_activation.py`

**修改方案：**

```python
# 修改前（第 7 行）：
#   - Simulation clock starts at _START_HOUR (08:00 HKT, morning commute).

# 修改後：可配置常量
_DEFAULT_START_HOUR: int = 8
_DEFAULT_PRIMETIME_HOURS: frozenset[int] = frozenset(range(18, 24))
_DEFAULT_PRIMETIME_MULTIPLIER: float = 1.5


class TemporalActivationService:
    def __init__(
        self,
        *,
        start_hour: int = _DEFAULT_START_HOUR,
        primetime_hours: frozenset[int] | None = _DEFAULT_PRIMETIME_HOURS,
        primetime_multiplier: float = _DEFAULT_PRIMETIME_MULTIPLIER,
    ):
        self._start_hour = start_hour
        self._primetime_hours = primetime_hours  # None = 無黃金時段
        self._primetime_multiplier = primetime_multiplier
```

修改 `should_activate()` 使用 instance 屬性而非模塊常量：

```python
    def should_activate(self, ...) -> bool:
        # ...
        if self._primetime_hours and hour in self._primetime_hours:
            multiplier = self._primetime_multiplier
        else:
            multiplier = 1.0
        # ...
```

**整合：** 在 `SimulationRunner.__init__()` 中根據 `sim_mode` 決定配置：

```python
if sim_mode == "kg_driven":
    # 虛構世界：無黃金時段
    self._temporal = TemporalActivationService(
        start_hour=6,
        primetime_hours=None,  # 關閉黃金時段
    )
else:
    # HK 模式：保持預設
    self._temporal = TemporalActivationService()
```

**測試：** 3 個測試 — 預設黃金時段生效、`primetime_hours=None` 時無倍率、自定義起始小時。

---

### 3.2 Lite Hooks 國際化

**問題：** `lite_hooks.py` 的情緒反應硬編碼繁體中文字串。

**文件：** `backend/app/services/lite_hooks.py`

**修改方案：**

```python
# 修改前：
_EMOTIONAL_REACTIONS = ["憤怒", "焦慮", "希望", ...]

# 修改後：雙語映射
_EMOTIONAL_REACTIONS_ZH = ["憤怒", "焦慮", "希望", "恐懼", "期待", "不滿"]
_EMOTIONAL_REACTIONS_EN = ["anger", "anxiety", "hope", "fear", "anticipation", "discontent"]

def _get_emotional_reactions(locale: str = "zh-HK") -> list[str]:
    if locale.startswith("en"):
        return _EMOTIONAL_REACTIONS_EN
    return _EMOTIONAL_REACTIONS_ZH
```

在所有使用 `_EMOTIONAL_REACTIONS` 嘅地方改為呼叫 `_get_emotional_reactions()`，locale 從 `KGSessionState` 或 scenario config 傳入。

**測試：** 2 個測試 — zh 返回中文、en 返回英文。

---

### 3.3 虛構世界 Alias 擴展

**問題：** `entity_extractor.py` 的 `_ALIAS_MAP` 只覆蓋現實世界實體。

**文件：** `backend/app/services/entity_extractor.py`

**修改方案 — LLM 動態生成 alias map：**

```python
# entity_extractor.py 新增方法

async def _generate_dynamic_aliases(
    self,
    nodes: list[dict],
    scenario_description: str,
) -> dict[str, str]:
    """Generate scenario-specific alias mappings via LLM.

    For Harry Potter: {"harry james potter": "harry potter",
                       "he who must not be named": "voldemort",
                       "the boy who lived": "harry potter"}
    """
    if len(nodes) < 3:
        return {}

    node_titles = [n.get("title", "") for n in nodes[:50]]
    prompt = f"""Given these entity names from a scenario about: {scenario_description[:500]}

Entities: {node_titles}

Generate alias mappings where different names refer to the same entity.
Return JSON: {{"alias": "canonical_name", ...}}
Only include confident mappings. Max 30 entries."""

    result = await self._llm.chat_json([
        {"role": "system", "content": "Return valid JSON only."},
        {"role": "user", "content": prompt},
    ])
    if isinstance(result, dict):
        return {k.lower(): v.lower() for k, v in result.items()}
    return {}
```

在 `extract()` 完成後、`_deduplicate_nodes()` 之前呼叫，將動態 aliases 合併到 `_ALIAS_MAP`：

```python
dynamic_aliases = await self._generate_dynamic_aliases(nodes, seed_text)
merged_aliases = {**_ALIAS_MAP, **dynamic_aliases}
nodes = self._deduplicate_nodes(nodes, alias_map=merged_aliases)
```

修改 `_deduplicate_nodes()` 接受 `alias_map` 參數而非用模塊常量。

**測試：** 3 個測試 — LLM 返回 aliases 成功合併、LLM 失敗用原有 map、動態 alias 正確去重。

---

## Phase 4：DX & 產品打磨（第 5–6 週）

### 4.1 一鍵啟動腳本

**學自 MiroFish：** `npm run setup:all && npm run dev` 兩行搞掂。

**新建文件：** 項目根目錄 `package.json`

```json
{
  "name": "murmuroscope",
  "private": true,
  "scripts": {
    "setup": "cd frontend && npm install",
    "setup:backend": "cd backend && python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt",
    "setup:all": "npm run setup && npm run setup:backend",
    "dev": "concurrently \"npm run backend\" \"npm run frontend\"",
    "backend": "cd backend && uvicorn run:app --reload --port 5001",
    "frontend": "cd frontend && npm run dev",
    "test": "cd backend && python -m pytest tests/ -m 'not integration' -q",
    "test:all": "cd backend && python -m pytest tests/ -q"
  },
  "devDependencies": {
    "concurrently": "^9.0.0"
  }
}
```

**同時新建 `Makefile` 快捷指令（如尚未有）：**

確認已有 `make test`、`make test-all` 等。新增：

```makefile
.PHONY: setup
setup:
	cd frontend && npm install
	cd backend && pip install -r requirements.txt

.PHONY: dev
dev:
	@echo "Starting frontend (5173) + backend (5001)..."
	cd backend && uvicorn run:app --reload --port 5001 &
	cd frontend && npm run dev
```

**測試：** 手動驗證 `npm run setup:all && npm run dev` 能正常啟動。

---

### 4.2 預置 Demo 場景

**新建：** `backend/app/domain/presets/` 目錄

```
backend/app/domain/presets/
  harry_potter_1_3.json     # HP seed text + 推薦配置
  dream_of_red_chamber.json # 紅樓夢（對標 MiroFish demo）
  taiwan_strait_crisis.json # 地緣政治
```

每個 preset JSON：

```json
{
  "name": "Harry Potter Books 1-3",
  "name_zh": "哈利波特第 1-3 集",
  "seed_text": "In the first three books of Harry Potter...",
  "recommended_preset": "STANDARD",
  "recommended_agent_count": 40,
  "recommended_rounds": 25,
  "belief_topics": [
    {"id": "dark_arts_threat", "label": "Dark Arts Threat"},
    {"id": "authority_trust", "label": "Authority Trust"},
    {"id": "blood_purity", "label": "Blood Purity"},
    {"id": "friendship_loyalty", "label": "Friendship Loyalty"},
    {"id": "house_identity", "label": "House Identity"},
    {"id": "muggle_acceptance", "label": "Muggle Acceptance"}
  ]
}
```

**API 端點：**

```python
# backend/app/api/simulation.py 新增
@router.get("/presets", response_model=APIResponse)
async def list_presets() -> APIResponse:
    """List available demo presets."""
    presets_dir = Path(__file__).parent.parent / "domain" / "presets"
    presets = []
    for f in sorted(presets_dir.glob("*.json")):
        data = json.loads(f.read_text())
        presets.append({"id": f.stem, "name": data["name"], "name_zh": data.get("name_zh", "")})
    return APIResponse(success=True, data={"presets": presets})

@router.get("/presets/{preset_id}", response_model=APIResponse)
async def get_preset(preset_id: str) -> APIResponse:
    """Get a specific demo preset's full config."""
    f = Path(__file__).parent.parent / "domain" / "presets" / f"{preset_id}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="Preset not found")
    return APIResponse(success=True, data=json.loads(f.read_text()))
```

**前端：** 在 Home.vue 或 Step1 加「快速開始」按鈕，點擊後載入 preset 自動填入 seed text。

**測試：** 2 個測試 — list 返回正確數量、get 返回正確結構。

---

### 4.3 README 國際化

**新建：** `README-EN.md`（英文優先，仿照 MiroFish 格式）

內容要點：
- Hero section：一句話描述 + badge（stars, license, tests passing）
- 30 秒 Quick Start
- Architecture diagram（ASCII 或 Mermaid）
- Demo 視頻連結（錄製 2 分鐘 workflow）
- Feature comparison table
- API 概覽
- Contributing guide

---

## Phase 5：測試覆蓋 & 驗證（貫穿全程）

### 5.1 新增測試清單

每個 Phase 完成後必須新增嘅測試：

| Phase | 新增測試 | 數量 |
|-------|---------|------|
| 0.1 Admin 認證 | 7 端點 × (無 token + 非 admin + admin) | 21 |
| 0.2 WebSocket 認證 | 無 token + 無效 token + 正常 | 3 |
| 0.3 Workspace 所有權 | 非 member + 非 owner session + 正常 | 3 |
| 0.4 成本持久化 | 記錄 + 恢復 + 硬上限 | 3 |
| 0.5 速率限制 | 超限返回 429 | 1 |
| 0.6 Limit clamp | 大值被 clamp | 1 |
| 1.1 自動降級 | 觸發 + lite 運行 + 恢復 | 3 |
| 1.2 斷路器 | 正常 + 斷開 + HALF_OPEN + 恢復 | 4 |
| 1.3 輪超時 | slow hook 超時後繼續 | 1 |
| 2.1 人格演化 | 5 條規則 + clamp + 非進化輪 | 7 |
| 2.2 不對稱關係 | 對稱 + A→B + B→A + deception | 4 |
| 2.3 信念主題 | 正常 + 失敗 + 上限 | 3 |
| 3.1 時間參數化 | 預設 + 無黃金 + 自定義 | 3 |
| 3.2 Lite 國際化 | zh + en | 2 |
| 3.3 動態 Alias | 成功 + 失敗 + 去重 | 3 |
| 4.2 Presets | list + get | 2 |
| **總計** | | **~64 個新測試** |

### 5.2 覆蓋率目標

```bash
# 運行覆蓋率報告
make test-cov

# 目標：
# - 新增代碼：90%+ 覆蓋
# - 整體項目：≥80%（現有 2729 測試 + 64 新測試 ≈ 2793）
```

---

## 附錄 A：文件清單速查

### 需修改嘅現有文件

| 文件 | Phase | 修改內容 |
|------|-------|---------|
| `backend/app/api/simulation.py` | 0.1, 0.5, 4.2 | Admin 認證 + 速率限制 + presets 端點 |
| `backend/app/api/ws.py` | 0.2 | WebSocket 必須認證 |
| `backend/app/api/workspace.py` | 0.3 | 所有權驗證 |
| `backend/app/api/auth.py` | 0.1 | UserProfile 加 is_admin + validate_token 共用函數 |
| `backend/app/services/cost_tracker.py` | 0.4 | DB 持久化 + 啟動恢復 |
| `backend/app/__init__.py` | 0.4 | 啟動時呼叫 restore_costs_from_db |
| `backend/app/services/simulation_hooks_kg_driven.py` | 1.1 | 自動降級邏輯 |
| `backend/app/utils/llm_client.py` | 1.2 | 斷路器整合 |
| `backend/app/services/simulation_runner.py` | 1.3 | 輪超時包裝 |
| `backend/app/models/relationship_state.py` | 2.2 | 新增 directional 字段 |
| `backend/app/services/relationship_engine.py` | 2.2 | 非對稱更新 |
| `backend/app/services/temporal_activation.py` | 3.1 | 參數化黃金時段 |
| `backend/app/services/lite_hooks.py` | 3.2 | 情緒反應國際化 |
| `backend/app/services/entity_extractor.py` | 3.3 | 動態 alias 生成 |
| `backend/app/models/kg_session_state.py` | 1.1 | 新增降級追蹤字段 |
| `backend/database/schema.sql` | 0.1, 0.4, 2.1, 2.2 | 新表 + ALTER TABLE |

### 需新建嘅文件

| 文件 | Phase | 用途 |
|------|-------|------|
| `backend/app/utils/pagination.py` | 0.6 | clamp_limit 函數 |
| `backend/app/utils/circuit_breaker.py` | 1.2 | 斷路器 |
| `backend/app/services/personality_evolution.py` | 2.1 | 人格動態演化 |
| `backend/app/services/belief_topic_generator.py` | 2.3 | 信念主題生成 |
| `backend/app/domain/presets/harry_potter_1_3.json` | 4.2 | HP demo preset |
| `backend/app/domain/presets/dream_of_red_chamber.json` | 4.2 | 紅樓夢 preset |
| `backend/app/domain/presets/taiwan_strait_crisis.json` | 4.2 | 地緣政治 preset |
| `README-EN.md` | 4.3 | 英文 README |
| 根目錄 `package.json`（如未有） | 4.1 | 一鍵啟動 |

---

## 附錄 B：驗收標準

### Tier 1 商用 MVP（Phase 0–3 完成後）

- [ ] 所有 admin 端點需要認證（無匿名訪問）
- [ ] WebSocket 拒絕無 token 連接
- [ ] Workspace 操作驗證所有權
- [ ] 成本追蹤重啟後不丟失
- [ ] 昂貴端點有速率限制
- [ ] LLM 全面故障 → 自動降級到 lite 模式（60 秒內）
- [ ] 斷路器阻止無效 API 調用風暴
- [ ] 每輪有 3 分鐘超時上限
- [ ] HP 1–3 seed text 可識別 ≥70% 主要角色
- [ ] Agent 人格每 5 輪有可觀察嘅演化
- [ ] 關係引擎支援非對稱信任
- [ ] 虛構世界無 HK 黃金時段干擾
- [ ] 30 輪模擬零崩潰
- [ ] 2793+ 測試全部通過
- [ ] 新增代碼覆蓋率 ≥90%

### Tier 2 發佈級（Phase 4–5 完成後）

- [ ] `npm run setup:all && npm run dev` 一鍵可用
- [ ] 3 個預置 demo 場景可即時體驗
- [ ] 英文 README 完整
- [ ] 整體覆蓋率 ≥80%
- [ ] E2E 測試覆蓋 5 步 workflow

---

## 附錄 C：風險 & 緩解

| 風險 | 概率 | 影響 | 緩解 |
|------|------|------|------|
| Admin 認證破壞現有部署 | 中 | 高 | 遷移腳本設第一個用戶為 admin |
| 斷路器誤觸發（正常延遲被判為故障） | 低 | 中 | threshold=10 足夠寬容 |
| 人格演化導致極端人格 | 低 | 中 | ±0.02 clamp + floor/ceiling |
| 動態 alias LLM 呼叫增加延遲 | 中 | 低 | 只在 extract() 初次呼叫，非每輪 |
| Schema migration 破壞現有數據 | 中 | 高 | 全用 ALTER TABLE ADD COLUMN（不刪除） |

---

**本計劃設計為可由另一個 AI agent 逐 Phase 執行。每個修改都指定了確切嘅文件、行號範圍、代碼片段同測試數量。**
