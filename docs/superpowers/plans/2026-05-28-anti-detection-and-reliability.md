# Anti-Detection & Reliability Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten the TGTG polling loop's anti-detection posture and per-user resilience: shorter base interval with night mode, per-user backoff, proactive token refresh, persistent Datadome cookie, skip-empty-favorites, error-rate metrics, and a cycle-duration log.

**Architecture:** All changes live in `app/TooGoodToGo.py` plus `app/database.py` (one new metrics table + one new column). New per-user state (cooldowns, last-favourite-count, last-cookie-hash) stays in-memory or in SQLite; no new modules — helpers are added as static methods on `TooGoodToGo` to keep them unit-testable without booting the bot. Tests live in `tests/test_logic.py`.

**Tech Stack:** Python 3 stdlib (`time`, `datetime`, `random`, `threading`), `tgtg` 0.19, SQLite (existing `app/database.py`), `pytest`.

---

## Context the engineer needs

- Read `app/TooGoodToGo.py` once before starting — especially `get_available_items_per_user` (the main loop), `_build_client`, `refresh_credentials`, `get_favourite_items`.
- The TGTG library does not enforce a polling rate. We do all of it.
- "Datadome cookie" lives on `TgtgClient.cookie` after a successful request. The library may rotate it after a 403 → cookie clear → re-fetch. Today we only persist `cookie` at login; we never write back a refreshed value during a polling cycle.
- The background polling thread runs in a separate `threading.Thread`. Any shared state must be guarded by an existing lock or a new one; `connected_clients` already uses `self._client_lock`.
- Tests use a `_bare_instance()` helper (see `tests/test_logic.py:58`) that skips `__init__` to avoid spinning threads. New tests should reuse it.
- Run tests with: `cd /home/battermanz/coding/bargainbites && python -m pytest tests/ -v`

## File structure (final state after this plan)

- `app/TooGoodToGo.py` — modified: new constants, helper static methods, updated polling loop, per-user cooldown dict, post-request cookie persist hook, periodic token refresh.
- `app/database.py` — modified: new `poller_metrics` table; new `last_favourite_count` column on `users_login_data` (or sibling table — see Task 3 for chosen approach).
- `tests/test_logic.py` — extended with one new test per behavioural change.

---

## Task 1: Shorter base loop interval (5–8 min)

**Files:**
- Modify: `app/TooGoodToGo.py:439-446` (the trailing `if not self.shutdown_flag.is_set(): ...` block)
- Test: `tests/test_logic.py`

- [ ] **Step 1: Write the failing test**

Add at the end of `tests/test_logic.py`:

```python
def test_compute_loop_delay_in_day_range():
    import TooGoodToGo
    # Day mode: 5–8 minutes (300–480 s) plus small noise (~±10s)
    for _ in range(50):
        delay = TooGoodToGo.TooGoodToGo._compute_loop_delay(hour=14)
        assert 280 <= delay <= 500, delay
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_logic.py::test_compute_loop_delay_in_day_range -v`
Expected: FAIL with `AttributeError: type object 'TooGoodToGo' has no attribute '_compute_loop_delay'`

- [ ] **Step 3: Add the helper method**

In `app/TooGoodToGo.py`, add this static method to the `TooGoodToGo` class (place it near `_user_needs_notifications`, around line 319):

```python
    DAY_LOOP_MIN_SECONDS = 300   # 5 min
    DAY_LOOP_MAX_SECONDS = 480   # 8 min

    @staticmethod
    def _compute_loop_delay(hour=None):
        """Return a randomized loop delay in seconds. `hour` is local hour 0-23.
        Night mode (01:00–06:59 local) is applied in a later task; for now the
        result is day-mode regardless of `hour`."""
        base = random.uniform(TooGoodToGo.DAY_LOOP_MIN_SECONDS,
                              TooGoodToGo.DAY_LOOP_MAX_SECONDS)
        noise = random.uniform(-10, 10)
        return base + noise
```

- [ ] **Step 4: Replace the trailing delay block to use the helper**

In `app/TooGoodToGo.py`, replace lines 439–446:

```python
            # Add random jitter to the main loop delay (between 13 and 17 minutes)
            if not self.shutdown_flag.is_set():
                base_delay = 900  # 15 minutes base
                jitter = random.uniform(-120, 120)  # ±2 minutes jitter
                # Add small random noise for less predictability
                noise = random.uniform(-10, 10)
                total_delay = base_delay + jitter + noise
                self.shutdown_flag.wait(timeout=total_delay)
```

with:

```python
            if not self.shutdown_flag.is_set():
                total_delay = self._compute_loop_delay(hour=datetime.now().hour)
                self.shutdown_flag.wait(timeout=total_delay)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_logic.py::test_compute_loop_delay_in_day_range -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/TooGoodToGo.py tests/test_logic.py
git commit -m "feat: shorten poll loop base interval to 5-8 minutes"
```

---

## Task 2: Night mode (longer delay 01:00–06:59 local)

**Files:**
- Modify: `app/TooGoodToGo.py` (the `_compute_loop_delay` added in Task 1)
- Test: `tests/test_logic.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_logic.py`:

```python
def test_compute_loop_delay_in_night_range():
    import TooGoodToGo
    # Night mode: 45–90 minutes (2700–5400 s) for hours 1..6 inclusive
    for h in (1, 3, 6):
        for _ in range(20):
            d = TooGoodToGo.TooGoodToGo._compute_loop_delay(hour=h)
            assert 2700 <= d <= 5400, (h, d)

def test_compute_loop_delay_boundary_hours_use_day_mode():
    import TooGoodToGo
    for h in (0, 7, 23):
        d = TooGoodToGo.TooGoodToGo._compute_loop_delay(hour=h)
        assert d <= 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_logic.py -v -k loop_delay`
Expected: the two new tests FAIL (returning day-mode values).

- [ ] **Step 3: Update `_compute_loop_delay` to apply night mode**

Replace the static method in `app/TooGoodToGo.py` with:

```python
    DAY_LOOP_MIN_SECONDS = 300    # 5 min
    DAY_LOOP_MAX_SECONDS = 480    # 8 min
    NIGHT_LOOP_MIN_SECONDS = 2700  # 45 min
    NIGHT_LOOP_MAX_SECONDS = 5400  # 90 min
    NIGHT_HOURS = (1, 2, 3, 4, 5, 6)

    @staticmethod
    def _compute_loop_delay(hour=None):
        """Return a randomized loop delay in seconds, with night-mode stretch
        applied between 01:00 and 06:59 local (`hour` in 1..6)."""
        if hour in TooGoodToGo.NIGHT_HOURS:
            return random.uniform(TooGoodToGo.NIGHT_LOOP_MIN_SECONDS,
                                  TooGoodToGo.NIGHT_LOOP_MAX_SECONDS)
        base = random.uniform(TooGoodToGo.DAY_LOOP_MIN_SECONDS,
                              TooGoodToGo.DAY_LOOP_MAX_SECONDS)
        noise = random.uniform(-10, 10)
        return base + noise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_logic.py -v -k loop_delay`
Expected: all three loop_delay tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/TooGoodToGo.py tests/test_logic.py
git commit -m "feat: add night-mode poll interval (45-90m, 01:00-06:59 local)"
```

---

## Task 3: Skip users whose favourites list was empty last cycle

**Strategy:** Persist `last_favourite_count` per user. If it was 0 *last cycle*, skip them this cycle (but every N=3 cycles probe them anyway so newly added favourites get picked up).

**Files:**
- Modify: `app/database.py` (new method + new table)
- Modify: `app/TooGoodToGo.py` (skip logic + write count after fetch)
- Test: `tests/test_logic.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_logic.py`:

```python
def test_should_skip_user_with_recent_empty_favourites():
    import TooGoodToGo
    T = TooGoodToGo.TooGoodToGo
    # Empty last time, hasn't reached probe interval -> skip
    assert T._should_skip_empty_user(last_count=0, cycles_since_probe=0) is True
    assert T._should_skip_empty_user(last_count=0, cycles_since_probe=2) is True
    # Probe forces inclusion every PROBE_EMPTY_USER_EVERY cycles
    assert T._should_skip_empty_user(last_count=0, cycles_since_probe=3) is False
    # Had favourites last time -> never skip
    assert T._should_skip_empty_user(last_count=5, cycles_since_probe=0) is False
    # No data yet -> never skip
    assert T._should_skip_empty_user(last_count=None, cycles_since_probe=0) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_logic.py::test_should_skip_user_with_recent_empty_favourites -v`
Expected: FAIL — no `_should_skip_empty_user`.

- [ ] **Step 3: Add the helper**

In `app/TooGoodToGo.py`, add near `_user_needs_notifications`:

```python
    PROBE_EMPTY_USER_EVERY = 3   # re-probe a user with 0 favourites every Nth cycle

    @staticmethod
    def _should_skip_empty_user(last_count, cycles_since_probe):
        """Skip a user whose last fetched favourites list was empty, unless we
        haven't probed them for PROBE_EMPTY_USER_EVERY cycles."""
        if last_count is None or last_count > 0:
            return False
        return cycles_since_probe < TooGoodToGo.PROBE_EMPTY_USER_EVERY
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_logic.py::test_should_skip_user_with_recent_empty_favourites -v`
Expected: PASS

- [ ] **Step 5: Add DB methods for persisting last_favourite_count**

Add to `app/database.py` (inside `Database` class):

```python
    def _ensure_favourite_counts_table(self):
        self._connect()
        self._local.cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_favourite_counts
        (user_id TEXT PRIMARY KEY,
         last_count INTEGER,
         cycles_since_probe INTEGER DEFAULT 0)
        ''')
        self._local.conn.commit()

    def get_favourite_count_state(self, user_id):
        """Return (last_count, cycles_since_probe). (None, 0) if unknown."""
        self._ensure_favourite_counts_table()
        self._local.cursor.execute(
            'SELECT last_count, cycles_since_probe FROM user_favourite_counts WHERE user_id = ?',
            (user_id,))
        row = self._local.cursor.fetchone()
        if row is None:
            return (None, 0)
        return (row[0], row[1] or 0)

    def set_favourite_count_state(self, user_id, last_count, cycles_since_probe):
        self._ensure_favourite_counts_table()
        self._local.cursor.execute(
            'INSERT OR REPLACE INTO user_favourite_counts VALUES (?, ?, ?)',
            (user_id, int(last_count), int(cycles_since_probe)))
        self._local.conn.commit()
```

- [ ] **Step 6: Wire skip logic into the polling loop**

In `app/TooGoodToGo.py`, change the user-keys filter block at lines 343–350 from:

```python
                # Only poll users who actually want at least one notification type.
                user_keys = [
                    uid for uid in users_login_data
                    if self._user_needs_notifications(self.db.get_user_settings(uid))
                ]
                if not user_keys:
                    self.logger.info("No users with active notifications - skipping API poll this cycle.")
                random.shuffle(user_keys)
```

to:

```python
                # Filter: notification settings on + not in empty-skip window.
                user_keys = []
                for uid in users_login_data:
                    if not self._user_needs_notifications(self.db.get_user_settings(uid)):
                        continue
                    last_count, cycles_since_probe = self.db.get_favourite_count_state(uid)
                    if self._should_skip_empty_user(last_count, cycles_since_probe):
                        self.db.set_favourite_count_state(uid, last_count, cycles_since_probe + 1)
                        continue
                    user_keys.append(uid)
                if not user_keys:
                    self.logger.info("No eligible users - skipping API poll this cycle.")
                random.shuffle(user_keys)
```

- [ ] **Step 7: Record the count after a successful fetch**

In `app/TooGoodToGo.py`, immediately after `available_items = self.get_favourite_items(key, client)` (around line 359), add:

```python
                        self.db.set_favourite_count_state(key, len(available_items), 0)
```

- [ ] **Step 8: Run the test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS (existing + new).

- [ ] **Step 9: Commit**

```bash
git add app/TooGoodToGo.py app/database.py tests/test_logic.py
git commit -m "feat: skip empty-favourite users with periodic re-probe"
```

---

## Task 4: Per-user captcha cooldown (replace global 5-min wait)

**Strategy:** Track `cooldown_until: dict[user_id -> epoch_seconds]` in memory. When a user hits a captcha/Datadome error, set them on cooldown for 30–60 min (jittered). Skip users still on cooldown at the top of the loop. Remove the global `shutdown_flag.wait(5*60)`.

**Files:**
- Modify: `app/TooGoodToGo.py`
- Test: `tests/test_logic.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_logic.py`:

```python
def test_user_cooldown_skip_and_expiry(monkeypatch):
    import TooGoodToGo, time
    inst = _bare_instance()
    inst._user_cooldowns = {}
    now = 1_000_000
    monkeypatch.setattr(TooGoodToGo.time, "time", lambda: now)
    inst._set_user_cooldown("u1", min_seconds=1800, max_seconds=1800)
    assert inst._is_user_on_cooldown("u1") is True
    assert inst._is_user_on_cooldown("u2") is False
    monkeypatch.setattr(TooGoodToGo.time, "time", lambda: now + 1801)
    assert inst._is_user_on_cooldown("u1") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_logic.py::test_user_cooldown_skip_and_expiry -v`
Expected: FAIL — methods don't exist.

- [ ] **Step 3: Add cooldown helpers**

In `app/TooGoodToGo.py`, add inside the class (near the static helpers):

```python
    CAPTCHA_COOLDOWN_MIN = 1800   # 30 min
    CAPTCHA_COOLDOWN_MAX = 3600   # 60 min

    def _set_user_cooldown(self, user_id, min_seconds=None, max_seconds=None):
        lo = self.CAPTCHA_COOLDOWN_MIN if min_seconds is None else min_seconds
        hi = self.CAPTCHA_COOLDOWN_MAX if max_seconds is None else max_seconds
        self._user_cooldowns[user_id] = time.time() + random.uniform(lo, hi)

    def _is_user_on_cooldown(self, user_id):
        until = self._user_cooldowns.get(user_id)
        if until is None:
            return False
        if time.time() >= until:
            self._user_cooldowns.pop(user_id, None)
            return False
        return True
```

- [ ] **Step 4: Initialize the dict in `__init__`**

In `app/TooGoodToGo.py`, add to `__init__` right after `self._client_lock = Lock()` (line 32):

```python
        self._user_cooldowns = {}  # user_id -> epoch seconds when cooldown expires
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_logic.py::test_user_cooldown_skip_and_expiry -v`
Expected: PASS

- [ ] **Step 6: Use cooldown in the loop, remove global wait**

In `app/TooGoodToGo.py`, in the user-keys filter loop (modified in Task 3), add a cooldown check before appending. Change:

```python
                    if self._should_skip_empty_user(last_count, cycles_since_probe):
                        self.db.set_favourite_count_state(uid, last_count, cycles_since_probe + 1)
                        continue
                    user_keys.append(uid)
```

to:

```python
                    if self._should_skip_empty_user(last_count, cycles_since_probe):
                        self.db.set_favourite_count_state(uid, last_count, cycles_since_probe + 1)
                        continue
                    if self._is_user_on_cooldown(uid):
                        continue
                    user_keys.append(uid)
```

Then in the per-user `except Exception as e:` block (lines 411–421), change:

```python
                    except Exception as e:
                        err_str = str(e).lower()
                        if "captcha" in err_str:
                            self.logger.warning(f"Captcha/Datadome block while polling user {key}; backing off 5 minutes.")
                            self.shutdown_flag.wait(timeout=5 * 60)
                        self.logger.error(f"Error processing user {key}: {e}")
                        consecutive_errors += 1
                        if consecutive_errors >= max_consecutive_errors:
                            self.logger.critical(f"Reached max consecutive errors ({max_consecutive_errors}). Pausing processing.")
                            break
                        continue
```

to:

```python
                    except Exception as e:
                        err_str = str(e).lower()
                        if "captcha" in err_str:
                            self._set_user_cooldown(key)
                            self.logger.warning(
                                f"Captcha/Datadome for user {key}; per-user cooldown set "
                                f"until {datetime.fromtimestamp(self._user_cooldowns[key]).isoformat(timespec='seconds')}."
                            )
                        self.logger.error(f"Error processing user {key}: {e}")
                        consecutive_errors += 1
                        if consecutive_errors >= max_consecutive_errors:
                            self.logger.critical(f"Reached max consecutive errors ({max_consecutive_errors}). Pausing processing.")
                            break
                        continue
```

- [ ] **Step 7: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/TooGoodToGo.py tests/test_logic.py
git commit -m "feat: per-user captcha cooldown (30-60m), drop global 5-min pause"
```

---

## Task 5: Reset `consecutive_errors` on a successful user fetch

**Files:**
- Modify: `app/TooGoodToGo.py`
- Test: existing tests cover the surrounding code; behaviour validated by inspection (no clean unit-test seam without bigger refactor — note this in the commit message).

- [ ] **Step 1: Locate the success path**

In `app/TooGoodToGo.py`, immediately after the `self.db.set_favourite_count_state(key, len(available_items), 0)` line added in Task 3, add:

```python
                        consecutive_errors = 0
```

- [ ] **Step 2: Run the test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS (no regressions).

- [ ] **Step 3: Commit**

```bash
git add app/TooGoodToGo.py
git commit -m "fix: reset consecutive_errors after a successful user fetch"
```

---

## Task 6: Persist refreshed Datadome cookie after each successful fetch

**Strategy:** After `get_items()` succeeds, the library may have rotated `client.cookie`. Compare against the stored credentials; if different, persist.

**Files:**
- Modify: `app/TooGoodToGo.py`
- Test: `tests/test_logic.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_logic.py`:

```python
def test_persist_cookie_if_changed_writes_only_on_change():
    inst = _bare_instance()
    saved = []

    class FakeDB:
        def save_users_login_data(self, data):
            saved.append({k: dict(v) for k, v in data.items()})

    inst.db = FakeDB()
    inst.users_login_data = {"u1": {"access_token": "AT", "refresh_token": "RT", "cookie": "old"}}

    class FakeClient:
        access_token = "AT"
        refresh_token = "RT"
        cookie = "old"  # unchanged

    inst._persist_cookie_if_changed("u1", FakeClient())
    assert saved == []  # nothing written

    FakeClient.cookie = "new"
    inst._persist_cookie_if_changed("u1", FakeClient())
    assert len(saved) == 1
    assert saved[0]["u1"]["cookie"] == "new"
    assert inst.users_login_data["u1"]["cookie"] == "new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_logic.py::test_persist_cookie_if_changed_writes_only_on_change -v`
Expected: FAIL — method missing.

- [ ] **Step 3: Add the method**

In `app/TooGoodToGo.py`, add inside the class (near `refresh_credentials`):

```python
    def _persist_cookie_if_changed(self, user_id, client):
        """If the client's Datadome cookie differs from what we have stored,
        write it back. Token fields may also rotate — persist the whole creds."""
        stored = self.users_login_data.get(user_id)
        if not stored:
            return
        new_cookie = getattr(client, "cookie", None)
        new_access = getattr(client, "access_token", None)
        new_refresh = getattr(client, "refresh_token", None)
        if (new_cookie == stored.get("cookie")
                and new_access == stored.get("access_token")
                and new_refresh == stored.get("refresh_token")):
            return
        self.users_login_data[user_id] = {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "cookie": new_cookie,
        }
        self.db.save_users_login_data({user_id: self.users_login_data[user_id]})
```

- [ ] **Step 4: Call it after each successful fetch**

In `app/TooGoodToGo.py`, after the `consecutive_errors = 0` line added in Task 5, add:

```python
                        self._persist_cookie_if_changed(key, client)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_logic.py::test_persist_cookie_if_changed_writes_only_on_change -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/TooGoodToGo.py tests/test_logic.py
git commit -m "feat: persist rotated TGTG/Datadome cookie after each fetch"
```

---

## Task 7: Proactive token refresh during the idle window

**Strategy:** TGTG access tokens live 4 hours. Right before the loop sleeps, refresh any client whose `last_time_token_refreshed` is older than `ACCESS_TOKEN_REFRESH_AFTER_SECONDS` (e.g. 3.5 hours). Reuses existing `refresh_credentials`.

**Files:**
- Modify: `app/TooGoodToGo.py`
- Test: `tests/test_logic.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_logic.py`:

```python
def test_should_refresh_access_token_by_age():
    import TooGoodToGo, datetime as _dt
    T = TooGoodToGo.TooGoodToGo
    now = _dt.datetime(2026, 5, 28, 12, 0, 0)
    fresh = _dt.datetime(2026, 5, 28, 10, 0, 0)   # 2 h old
    stale = _dt.datetime(2026, 5, 28, 8, 0, 0)    # 4 h old
    assert T._should_refresh_access_token(now, fresh) is False
    assert T._should_refresh_access_token(now, stale) is True
    assert T._should_refresh_access_token(now, None) is False  # no client / unknown
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_logic.py::test_should_refresh_access_token_by_age -v`
Expected: FAIL.

- [ ] **Step 3: Add the helper**

In `app/TooGoodToGo.py`, add to the class:

```python
    ACCESS_TOKEN_REFRESH_AFTER_SECONDS = 3 * 3600 + 30 * 60  # 3h30 — refresh before 4h expiry

    @staticmethod
    def _should_refresh_access_token(now, last_refreshed):
        if last_refreshed is None:
            return False
        return (now - last_refreshed).total_seconds() >= TooGoodToGo.ACCESS_TOKEN_REFRESH_AFTER_SECONDS
```

- [ ] **Step 4: Add the per-cycle refresh pass**

In `app/TooGoodToGo.py`, add a method:

```python
    def _refresh_stale_tokens(self):
        """Proactively refresh access tokens approaching their 4h lifetime so a
        refresh doesn't land in the middle of get_items()."""
        now = datetime.now()
        with self._client_lock:
            user_ids = list(self.connected_clients.keys())
        for uid in user_ids:
            with self._client_lock:
                client = self.connected_clients.get(uid)
            last_refreshed = getattr(client, "last_time_token_refreshed", None)
            if not self._should_refresh_access_token(now, last_refreshed):
                continue
            try:
                self.refresh_credentials(uid)
                self.logger.info(f"Proactively refreshed token for user {uid}")
            except Exception as e:
                self.logger.warning(f"Proactive token refresh failed for {uid}: {e}")
```

- [ ] **Step 5: Call it just before the idle wait**

In `app/TooGoodToGo.py`, immediately before the `if not self.shutdown_flag.is_set():` that schedules `_compute_loop_delay`, add:

```python
            if not self.shutdown_flag.is_set():
                self._refresh_stale_tokens()
```

(So the structure becomes: refresh-tokens block → compute-delay block.)

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/TooGoodToGo.py tests/test_logic.py
git commit -m "feat: proactively refresh TGTG access tokens before 4h expiry"
```

---

## Task 8: Daily 403/captcha counters in DB

**Strategy:** New `poller_metrics` table keyed by `(date, metric)`. Increment on captcha/403 events.

**Files:**
- Modify: `app/database.py` (new table + helpers)
- Modify: `app/TooGoodToGo.py` (increment on captcha + on 401/403)
- Test: `tests/test_logic.py` (integration-style with a tmp SQLite file)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_logic.py`:

```python
def test_metrics_increment_and_get(tmp_path):
    from database import Database
    db_file = tmp_path / "metrics.db"
    db = Database(str(db_file))
    db.increment_metric("captcha", day="2026-05-28")
    db.increment_metric("captcha", day="2026-05-28")
    db.increment_metric("http_401", day="2026-05-28")
    assert db.get_metric("captcha", day="2026-05-28") == 2
    assert db.get_metric("http_401", day="2026-05-28") == 1
    assert db.get_metric("captcha", day="2026-05-27") == 0
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_logic.py::test_metrics_increment_and_get -v`
Expected: FAIL.

- [ ] **Step 3: Add the table + helpers**

In `app/database.py`, append to the `Database` class:

```python
    def _ensure_poller_metrics_table(self):
        self._connect()
        self._local.cursor.execute('''
        CREATE TABLE IF NOT EXISTS poller_metrics
        (day TEXT, metric TEXT, value INTEGER DEFAULT 0,
         PRIMARY KEY (day, metric))
        ''')
        self._local.conn.commit()

    def increment_metric(self, metric, day):
        self._ensure_poller_metrics_table()
        self._local.cursor.execute(
            'INSERT INTO poller_metrics(day, metric, value) VALUES (?, ?, 1) '
            'ON CONFLICT(day, metric) DO UPDATE SET value = value + 1',
            (day, metric))
        self._local.conn.commit()

    def get_metric(self, metric, day):
        self._ensure_poller_metrics_table()
        self._local.cursor.execute(
            'SELECT value FROM poller_metrics WHERE day = ? AND metric = ?',
            (day, metric))
        row = self._local.cursor.fetchone()
        return int(row[0]) if row else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_logic.py::test_metrics_increment_and_get -v`
Expected: PASS.

- [ ] **Step 5: Increment captcha metric in the loop**

In `app/TooGoodToGo.py`, in the per-user `except` block (after `self._set_user_cooldown(key)`), add a sibling line:

```python
                            self.db.increment_metric("captcha", day=date.today().isoformat())
```

- [ ] **Step 6: Increment http_401 metric in `get_favourite_items`**

In `app/TooGoodToGo.py`, in `get_favourite_items`, inside the `if "401" in error_str or "unauthorized" in error_str:` branch (line ~234), as the first line of that branch:

```python
                    self.db.increment_metric("http_401", day=date.today().isoformat())
```

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/TooGoodToGo.py app/database.py tests/test_logic.py
git commit -m "feat: track daily captcha/401 counters for detection telemetry"
```

---

## Task 9: Log per-cycle duration and per-user spacing health

**Strategy:** Wrap the per-cycle work in a timer; log total cycle duration plus user count, so overlap with the loop interval becomes visible.

**Files:**
- Modify: `app/TooGoodToGo.py`
- Test: none — purely an observability change; verify by reading log output once.

- [ ] **Step 1: Mark cycle start**

In `app/TooGoodToGo.py`, inside `get_available_items_per_user`, at the very top of the outer `try:` (right after `consecutive_errors = 0`), add:

```python
                cycle_start = time.monotonic()
```

- [ ] **Step 2: Log on cycle end**

In `app/TooGoodToGo.py`, immediately after `self.db.save_available_items_favorites(available_items_favorites)` (line ~426), add:

```python
                cycle_seconds = time.monotonic() - cycle_start
                self.logger.info(
                    f"Cycle complete: users_polled={len(user_keys)} "
                    f"duration={cycle_seconds:.1f}s")
```

- [ ] **Step 3: Run the test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 4: Smoke-check manually (optional)**

If a dev runtime is available: start the bot, watch logs for a "Cycle complete" line within ~10 minutes.

- [ ] **Step 5: Commit**

```bash
git add app/TooGoodToGo.py
git commit -m "chore: log per-cycle duration and users polled"
```

---

## Final verification

- [ ] **Step 1: Run the entire suite**

Run: `python -m pytest tests/ -v`
Expected: ALL tests PASS.

- [ ] **Step 2: Syntax check the changed modules**

Run: `python -c "import sys; sys.path.insert(0, 'app'); import TooGoodToGo, database; print('OK')"`
Expected: prints `OK` with no traceback.

- [ ] **Step 3: Confirm git log shows the planned series**

Run: `git log --oneline -n 12`
Expected: ~9 new commits since the plan started, in the order of the tasks above.

---

## Notes for the implementer

- **Random.uniform** is used throughout for jitter; never replace with fixed values — the jitter is a deliberate anti-fingerprinting signal.
- **`time.time()` vs `time.monotonic()`**: Task 4 uses `time.time()` because cooldown deadlines must survive a system clock check across long sleeps; Task 9 uses `time.monotonic()` because it measures an elapsed interval where wall-clock jumps would corrupt the metric.
- **Don't parallelize per-user requests.** Sequential with 20–40 s spacing is the bot-detection lever — preserve it.
- **Don't extend the captcha cooldown across restarts.** It's in-memory by design; a restart that hits captcha immediately is a louder signal than a missed cooldown.
- If `tests/test_logic.py` already imports `time` at module level, drop the inline `import time` in the Task 4 test.
