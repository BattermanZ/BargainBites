# TGTG 0.19.0 Migration & Bot Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate BargainBites from `tgtg==0.18.2` (email-link login, no anti-bot bypass) to `tgtg==0.19.0` (Datadome bypass) by adopting the PIN-based login flow, then fix the latent shared-client race, add smart polling, and harden the poll loop.

**Architecture:** BargainBites is a multi-user Telegram bot. `app/main.py` wires logging/env/signals and launches `setup_bot` (handlers in `app/Telegram.py`) plus a `TooGoodToGo` core (`app/TooGoodToGo.py`) that owns a background polling `Thread`, an async message queue, and a SQLite `Database` (`app/database.py`). The TGTG library (`tgtg` on PyPI) is a dependency, not vendored. The 0.19.0 login flow blocks on `input()` for a PIN, so we intercept the `polling_id` before that and complete login with a PIN the user sends via `/pin`. We keep ephemeral pending-login state in memory (no DB), make TGTG clients per-user locals instead of a shared `self.client`, and only hit the API for users who actually want notifications.

**Tech Stack:** Python 3.11+, `pyTelegramBotAPI` (`AsyncTeleBot`), `tgtg==0.19.0`, SQLite (`sqlite3`), `python-dotenv`, Docker. Tests: `pytest`.

---

## Background: why this ordering

The version bump and the login rewrite **must land together** (Tasks 1–3). On 0.19.0, `TgtgClient.get_credentials()` → `login()` → `start_polling()` calls `input("Enter PIN from email: ")`, which throws `EOFError` in the container (no TTY). Your current `new_user()` (`app/TooGoodToGo.py:83-84`) relies on `get_credentials()` completing headlessly, so a naive bump breaks all logins. After login works, Tasks 4–9 fix independent correctness/efficiency issues uncovered during review.

## File Structure

- `requirements.txt` — bump `tgtg` to `0.19.0` (modify line 33).
- `requirements-dev.txt` — **new**, test dependencies (`pytest`).
- `tests/conftest.py` — **new**, puts `app/` on `sys.path` so tests can `import TooGoodToGo`.
- `tests/test_logic.py` — **new**, unit tests for pure helpers extracted from `TooGoodToGo`.
- `app/TooGoodToGo.py` — the bulk of changes: login flow, per-user clients, smart polling, captcha backoff, parsing guards, pruning, cleanup.
- `app/Telegram.py` — add `/pin` handler, update help text.
- `app/database.py` — remove stray `print` debug (line 171).

---

### Task 1: Test infrastructure

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_logic.py`

- [ ] **Step 1: Create dev requirements**

Create `requirements-dev.txt`:

```
-r requirements.txt
pytest==8.3.4
```

- [ ] **Step 2: Create conftest that exposes the app package**

Create `tests/conftest.py`:

```python
import os
import sys

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
```

- [ ] **Step 3: Create a smoke test that imports the module**

Create `tests/test_logic.py`:

```python
def test_import_toogoodtogo_module():
    import TooGoodToGo
    assert hasattr(TooGoodToGo, "TooGoodToGo")
```

- [ ] **Step 4: Install and run**

Run: `pip install -r requirements-dev.txt && python -m pytest tests/ -v`
Expected: PASS (1 passed). Importing the module has no side effects today; if this fails with a `tgtg.USER_AGENTS` error, that monkeypatch is removed in Task 2.

- [ ] **Step 5: Commit**

```bash
git add requirements-dev.txt tests/conftest.py tests/test_logic.py
git commit -m "test: add pytest infrastructure and import smoke test"
```

---

### Task 2: Bump tgtg to 0.19.0 and drop the user-agent monkeypatch

**Files:**
- Modify: `requirements.txt:33`
- Modify: `app/TooGoodToGo.py:7-20`

**Why:** 0.19.0 fetches the latest APK version itself via `get_last_apk_version()` and formats the user agent with it. The hardcoded `tgtg.USER_AGENTS = [...]` pins a stale string and disables that lookup.

- [ ] **Step 1: Bump the dependency**

In `requirements.txt`, change line 33 from `tgtg==0.18.2` to:

```
tgtg==0.19.0
```

- [ ] **Step 2: Remove the monkeypatch and the now-unused import**

In `app/TooGoodToGo.py`, the current top of file is:

```python
from tgtg import TgtgClient
import tgtg
from database import Database
import asyncio
from queue import Queue
import queue
import random
from tgtg.exceptions import TgtgAPIError
import os

# Override TGTG user agents with latest version
tgtg.USER_AGENTS = [
    "TGTG/25.2.0 Dalvik/2.1.0 (Linux; U; Android 15; sdk_gphone64_x86_64 Build/AE3A.240806.043)",
]
```

Replace it with (drop the `import tgtg` and the monkeypatch block; add `TgtgLoginError` which later tasks use):

```python
from tgtg import TgtgClient
from database import Database
import asyncio
from queue import Queue
import queue
import random
from tgtg.exceptions import TgtgAPIError, TgtgLoginError
import os
```

- [ ] **Step 3: Install the new version**

Run: `pip install -r requirements.txt`
Expected: `Successfully installed tgtg-0.19.0`.

- [ ] **Step 4: Verify the module still imports**

Run: `python -m pytest tests/test_logic.py::test_import_toogoodtogo_module -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt app/TooGoodToGo.py
git commit -m "feat: upgrade tgtg to 0.19.0 and remove user-agent monkeypatch"
```

---

### Task 3: PIN-based login flow

**Files:**
- Modify: `app/TooGoodToGo.py` (`__init__`, `new_user`, `relogin`; add `complete_login_with_pin`, `_credentials_from_client`)
- Modify: `app/Telegram.py` (add `/pin` handler; update `/login`, `/relogin`, help text)
- Test: `tests/test_logic.py`

**Why:** On 0.19.0, `get_credentials()` blocks on `input()` for a PIN. We initiate login by POSTing to the auth endpoint ourselves, capture the `polling_id`, stash the client in memory, and finish via `_auth_by_pin(polling_id, pin)` when the user sends `/pin`.

- [ ] **Step 1: Write the failing test for credential extraction**

Add to `tests/test_logic.py`:

```python
def test_credentials_from_client_reads_token_fields():
    import TooGoodToGo

    class FakeClient:
        access_token = "AT"
        refresh_token = "RT"
        cookie = "datadome=abc"

    creds = TooGoodToGo.TooGoodToGo._credentials_from_client(FakeClient())
    assert creds == {"access_token": "AT", "refresh_token": "RT", "cookie": "datadome=abc"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_logic.py::test_credentials_from_client_reads_token_fields -v`
Expected: FAIL with `AttributeError: ... has no attribute '_credentials_from_client'`.

- [ ] **Step 3: Add the pending-login store to `__init__`**

In `app/TooGoodToGo.py`, inside `__init__`, immediately after the line `self.connected_clients = {}` (currently `app/TooGoodToGo.py:36`), add:

```python
        self.pending_logins = {}  # telegram_user_id (str) -> {"client", "polling_id", "email"}
```

- [ ] **Step 4: Replace `new_user` and `relogin`, add the two new methods**

In `app/TooGoodToGo.py`, replace the entire current `new_user` method (`app/TooGoodToGo.py:72-90`) and `relogin` method (`app/TooGoodToGo.py:92-100`) with:

```python
    @staticmethod
    def _credentials_from_client(client):
        return {
            "access_token": client.access_token,
            "refresh_token": client.refresh_token,
            "cookie": client.cookie,
        }

    async def new_user(self, telegram_user_id, email, force_relogin=False):
        telegram_user_id = str(telegram_user_id)
        if telegram_user_id in self.users_login_data and not force_relogin:
            await self.send_message(telegram_user_id, "This chat is already logged in! To re-login, use /relogin")
            return
        # Run the blocking HTTP call off the event loop.
        await asyncio.get_event_loop().run_in_executor(
            None, self._initiate_login, telegram_user_id, email
        )

    def _initiate_login(self, telegram_user_id, email):
        """Blocking: POST authByEmail, capture polling_id, stash client. Runs in executor/thread."""
        from tgtg import AUTH_BY_EMAIL_ENDPOINT
        try:
            client = TgtgClient(email=email)
            response = client._post(
                client._get_url(AUTH_BY_EMAIL_ENDPOINT),
                json={"device_type": client.device_type, "email": client.email},
            )
            if response.status_code != 200:
                raise TgtgLoginError(response.status_code, response.content)

            login_resp = response.json()
            state = login_resp.get("state")
            if state == "WAIT":
                self.pending_logins[telegram_user_id] = {
                    "client": client,
                    "polling_id": login_resp["polling_id"],
                    "email": email,
                }
                self.logger.info(f"Login initiated for {telegram_user_id} - waiting for PIN")
                self.message_queue_text(
                    telegram_user_id,
                    "📩 Check your email for a *login PIN code* from Too Good To Go.\n\n"
                    "Then send it here:\n`/pin 12345`",
                )
            elif state == "TERMS":
                self.message_queue_text(
                    telegram_user_id,
                    "❌ This email is not linked to a TGTG account. Please sign up in the TGTG app first.",
                )
            else:
                self.message_queue_text(telegram_user_id, f"❌ Unexpected login state: {state}")
        except TgtgAPIError as e:
            self.logger.error(f"Login rate-limited for {telegram_user_id}: {e}")
            self.message_queue_text(telegram_user_id, "❌ Too many requests. Please try again later.")
        except TgtgLoginError as e:
            self.logger.warning(f"Login blocked/failed for {telegram_user_id}: {e}")
            self.message_queue_text(
                telegram_user_id,
                "🔒 *Login blocked by TGTG (anti-bot).* Try again later, or from a different network.",
            )
        except Exception as e:
            self.logger.error(f"Unexpected error initiating login for {telegram_user_id}: {e}")
            self.message_queue_text(telegram_user_id, "❌ An error occurred during login. Please try again later.")

    def complete_login_with_pin(self, telegram_user_id, pin):
        """Blocking: finish a pending login with the emailed PIN. Runs in executor/thread."""
        telegram_user_id = str(telegram_user_id)
        pending = self.pending_logins.pop(telegram_user_id, None)
        if not pending:
            self.message_queue_text(telegram_user_id, "⚠️ No pending login. Start with `/login email@example.com` first.")
            return
        try:
            client = pending["client"]
            client._auth_by_pin(pending["polling_id"], pin)
            credentials = self._credentials_from_client(client)
            self.add_user(telegram_user_id, credentials)
            self.logger.info(f"Login completed for {telegram_user_id}")
            self.message_queue_text(telegram_user_id, "✅ You are now logged in!")
        except TgtgLoginError as e:
            self.logger.error(f"PIN auth failed for {telegram_user_id}: {e}")
            self.pending_logins[telegram_user_id] = pending  # allow retry
            self.message_queue_text(telegram_user_id, "❌ Invalid or expired PIN. Check your email and resend `/pin 12345`.")
        except Exception as e:
            self.logger.error(f"Error completing login for {telegram_user_id}: {e}")
            self.message_queue_text(telegram_user_id, "❌ Login failed. Please try `/login` again.")

    async def relogin(self, telegram_user_id, email):
        telegram_user_id = str(telegram_user_id)
        if telegram_user_id in self.users_login_data:
            del self.users_login_data[telegram_user_id]
            self.db.save_users_login_data(self.users_login_data)
        await self.new_user(telegram_user_id, email, force_relogin=True)
```

- [ ] **Step 5: Add the `message_queue_text` helper used above**

`_initiate_login` / `complete_login_with_pin` run in a worker thread and cannot `await self.send_message`. Reuse the existing async message queue (drained by `process_message_queue`). The queue currently carries 5-tuples `(key, message, item_id, store_id, store_name)` for `send_message_with_link`. Add a plain-text path by allowing a 2-tuple `(key, message)`.

In `app/TooGoodToGo.py`, add this method right after `send_message_with_link` (`app/TooGoodToGo.py:64`):

```python
    def message_queue_text(self, telegram_user_id, message):
        """Thread-safe: enqueue a plain-text message for the async sender."""
        self.message_queue.put((str(telegram_user_id), message))
```

Then update `process_message_queue` (`app/TooGoodToGo.py:377-394`) to dispatch on tuple length. Replace its body with:

```python
    async def process_message_queue(self):
        while not self.shutdown_flag.is_set():
            try:
                payload = await asyncio.get_event_loop().run_in_executor(
                    None, self.message_queue.get, True, 1.0
                )
                try:
                    if len(payload) == 2:
                        key, message = payload
                        await self.send_message(key, message)
                    else:
                        key, message, item_id, store_id, store_name = payload
                        await self.send_message_with_link(key, message, item_id, store_id, store_name)
                    self.logger.info(f"Message sent to user {key}")
                except Exception as e:
                    self.logger.error(f"Error sending message: {e}")
                finally:
                    self.message_queue.task_done()
            except queue.Empty:
                pass
            except Exception as e:
                self.logger.error(f"Unexpected error in process_message_queue: {e}", exc_info=True)
                await asyncio.sleep(1)
```

- [ ] **Step 6: Run the credential-extraction test to verify it passes**

Run: `python -m pytest tests/test_logic.py::test_credentials_from_client_reads_token_fields -v`
Expected: PASS.

- [ ] **Step 7: Add the `/pin` handler and update help text in Telegram.py**

In `app/Telegram.py`, update the `/login` confirmation text and add a `/pin` handler. Replace the success branch of `send_login` (`app/Telegram.py:87`) — the line that begins `await bot.send_message(chat_id=message.chat.id, text="📩 Please open your mail account...` — with:

```python
            await bot.send_message(chat_id=message.chat.id, text="📩 You'll receive an email with a *PIN code* from Too Good To Go.\nReply here with `/pin 12345` to finish logging in.", parse_mode="Markdown")
```

Apply the identical replacement to the matching line in `send_relogin` (`app/Telegram.py:103`).

Then add this handler immediately after the `send_relogin` handler (after `app/Telegram.py:108`):

```python
    @bot.message_handler(commands=['pin'])
    async def send_pin(message):
        if not await check_authorization(message):
            return
        chat_id = str(message.chat.id)
        pin = message.text.replace('/pin', '').strip()
        if not pin:
            await bot.send_message(chat_id=message.chat.id, text="⚠️ Please provide the PIN from your email:\n`/pin 12345`", parse_mode="Markdown")
            return
        await bot.send_message(chat_id=message.chat.id, text="⏳ Verifying PIN...")
        import asyncio
        asyncio.get_event_loop().run_in_executor(None, tooGoodToGo.complete_login_with_pin, chat_id, pin)
```

Register the command in the menu: in `app/TooGoodToGo.py` `set_bot_commands` (`app/TooGoodToGo.py:46-54`), add a `/pin` entry right after the `/login` line:

```python
            types.BotCommand("/pin", "complete login with the PIN from your email"),
```

Update the help text in `app/Telegram.py` `send_welcome` (`app/Telegram.py:45-48`) — replace the block describing login:

```python
🔑 To login into the TooGoodToGo account for this group, enter 
*/login email@example.com*
_You will then receive an email with a confirmation link.
You do not need to enter a password._
```

with:

```python
🔑 To login, enter 
*/login email@example.com*
_You'll receive an email with a PIN code. Then send_ */pin 12345* _to finish. No password needed._
```

- [ ] **Step 8: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS (all green).

- [ ] **Step 9: Manual end-to-end login verification**

This flow makes real TGTG network calls and cannot be unit-tested. With a valid bot token and a real TGTG email in a scratch environment:

```bash
cd app && python main.py
```

In Telegram: send `/login your-real@email.com`, confirm the bot replies asking for a PIN, check the email for the PIN, send `/pin <code>`, and confirm `✅ You are now logged in!`. Then send `/info` and confirm it lists items (or "all sold out") without a 403/captcha error. If you see a Datadome/captcha block, that is network-IP related (Task 6 surfaces it gracefully), not a code bug.

- [ ] **Step 10: Commit**

```bash
git add app/TooGoodToGo.py app/Telegram.py tests/test_logic.py
git commit -m "feat: PIN-based login flow for tgtg 0.19.0"
```

---

### Task 4: Per-user TGTG clients (fix shared-client race)

**Files:**
- Modify: `app/TooGoodToGo.py` (`__init__`, replace `connect`/`get_favourite_items`/`refresh_credentials`; update `send_available_favourite_items_for_one_user` and the background loop)

**Why:** `self.client` is a single shared attribute mutated per-user by `connect()` (`app/TooGoodToGo.py:155,130,145`). The background `Thread` and an async `/info` can both reassign and read it concurrently, so one user's fetch can run on another user's client — items leak to the wrong chat. Fix: clients become per-user locals; the cache is keyed by user and guarded by a lock; `self.client` is removed.

- [ ] **Step 1: Replace shared-client state in `__init__`**

In `app/TooGoodToGo.py` `__init__`, remove the line `self.client = TgtgClient` (`app/TooGoodToGo.py:37`) and replace the `self.connected_clients = {}` line (`app/TooGoodToGo.py:36`) with:

```python
        self.connected_clients = {}   # user_id -> TgtgClient (per-user cache)
        self._client_lock = __import__("threading").Lock()
```

(`from threading import Thread, Event` is already imported at the top; using `__import__` here avoids touching the import line. Alternatively add `Lock` to that existing import — either is fine.)

- [ ] **Step 2: Replace `refresh_credentials`, `connect`, and `get_favourite_items`**

Replace all three methods (`app/TooGoodToGo.py:105-200`) with per-user, client-passing versions:

```python
    def _build_client(self, user_id):
        """Build (or reuse) a per-user TGTG client. Thread-safe. Returns a client or raises."""
        with self._client_lock:
            cached = self.connected_clients.get(user_id)
        if cached is not None:
            return cached
        creds = self.find_credentials_by_telegramUserID(user_id)
        if not creds:
            raise Exception(f"No credentials found for user ID: {user_id}")
        time.sleep(random.uniform(10, 20))  # rate-limit cushion on cold connect
        client = TgtgClient(
            access_token=creds["access_token"],
            refresh_token=creds["refresh_token"],
            cookie=creds["cookie"],
        )
        with self._client_lock:
            self.connected_clients[user_id] = client
        return client

    def refresh_credentials(self, user_id):
        """Refresh a user's credentials, persist them, return a fresh client or None."""
        try:
            creds = self.find_credentials_by_telegramUserID(user_id)
            if not creds:
                self.logger.error(f"No credentials found for user {user_id}")
                return None
            client = TgtgClient(
                access_token=creds["access_token"],
                refresh_token=creds["refresh_token"],
                cookie=creds["cookie"],
            )
            new_credentials = client.get_credentials()
            self.users_login_data[user_id] = new_credentials
            self.db.save_users_login_data(self.users_login_data)
            with self._client_lock:
                self.connected_clients[user_id] = client
            self.logger.info(f"Successfully refreshed credentials for user {user_id}")
            return client
        except Exception as e:
            self.logger.error(f"Failed to refresh credentials for user {user_id}: {e}")
            with self._client_lock:
                self.connected_clients.pop(user_id, None)
            return None

    def get_favourite_items(self, user_id, client):
        """Fetch favourites for a specific user/client, with retry, captcha and 401 handling."""
        max_retries = 3
        base_delay = 10
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    delay = base_delay * (2 ** attempt) + random.uniform(5, 15)
                    self.logger.warning(f"Retrying get_items for {user_id} after {delay:.2f}s...")
                    time.sleep(delay)
                return client.get_items()
            except TgtgAPIError as e:
                error_str = str(e).lower()
                if "401" in error_str or "unauthorized" in error_str:
                    self.logger.warning(f"401 for user {user_id}; attempting credential refresh")
                    refreshed = self.refresh_credentials(user_id)
                    if refreshed is None:
                        raise
                    client = refreshed
                    continue
                if "captcha" in error_str:
                    if attempt == max_retries - 1:
                        self.logger.error(f"Max retries reached for CAPTCHA (user {user_id})")
                        raise
                    continue
                if "404" in error_str:
                    self.logger.warning("Got 404, likely API endpoint issue")
                    raise
                self.logger.error(f"TGTG API error for {user_id}: {e}")
                raise
            except Exception as e:
                self.logger.error(f"Unexpected error in get_favourite_items for {user_id}: {e}")
                raise
        raise Exception(f"get_favourite_items exhausted retries for {user_id}")
```

Note: this **also fixes the dead 401-refresh path** (formerly placed on client construction, which never raises a 401). The old `connect(user_id)` method is gone — callers now use `_build_client`.

- [ ] **Step 3: Update `send_available_favourite_items_for_one_user`**

Replace `app/TooGoodToGo.py:241-258` with:

```python
    async def send_available_favourite_items_for_one_user(self, user_id):
        try:
            client = self._build_client(user_id)
            favourite_items = self.get_favourite_items(user_id, client)
            available_items = [item for item in favourite_items if item['items_available'] > 0 and not self.db.is_store_blacklisted(user_id, item['store']['store_id'])]
            if not available_items:
                await self.send_message(user_id, "Currently all your favorites are sold out or ignored 😕")
                return
            for item in available_items:
                message, item_id, store_id, store_name = self.format_message(item)
                await self.send_message_with_link(user_id, message, item_id, store_id, store_name)
            self.logger.info(f"Sent available items for user ID: {user_id}")
        except Exception as e:
            self.logger.error(f"Error sending available items: {e}")
            await self.send_message(user_id, "❌ An error occurred while fetching available items. Please try again later.")
```

- [ ] **Step 4: Update the background loop's connect/fetch calls**

In `get_available_items_per_user`, replace the per-user fetch block (`app/TooGoodToGo.py:282-289`) — the lines doing `self.connect(key)`, the sleep, and `available_items = self.get_favourite_items()` — with:

```python
                        client = self._build_client(key)
                        time.sleep(random.uniform(20, 40))
                        available_items = self.get_favourite_items(key, client)
```

- [ ] **Step 5: Run the suite (no behavior regressions on import/pure helpers)**

Run: `python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 6: Manual verification**

Run the bot, log in two different TGTG accounts in two Telegram chats, and send `/info` from both in quick succession. Confirm each chat receives only its own stores (the race fix). Also confirm a single `/info` still returns items.

- [ ] **Step 7: Commit**

```bash
git add app/TooGoodToGo.py
git commit -m "fix: per-user TGTG clients to remove shared-client race and fix 401 refresh"
```

---

### Task 5: Smart polling — skip the API when nobody wants notifications

**Files:**
- Modify: `app/TooGoodToGo.py` (add `_user_needs_notifications`; gate the loop)
- Test: `tests/test_logic.py`

**Why:** The loop polls every logged-in user every cycle (`app/TooGoodToGo.py:274-277`) regardless of whether they've enabled any notification type. Skipping users whose settings are all `0` cuts API calls and detection risk.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_logic.py`:

```python
import pytest

@pytest.mark.parametrize("settings,expected", [
    ({"sold_out": 0, "new_stock": 0, "stock_reduced": 0, "stock_increased": 0}, False),
    ({"sold_out": 0, "new_stock": 1, "stock_reduced": 0, "stock_increased": 0}, True),
    ({}, False),
])
def test_user_needs_notifications(settings, expected):
    import TooGoodToGo
    assert TooGoodToGo.TooGoodToGo._user_needs_notifications(settings) is expected
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_logic.py::test_user_needs_notifications -v`
Expected: FAIL with `AttributeError: ... '_user_needs_notifications'`.

- [ ] **Step 3: Add the static helper**

In `app/TooGoodToGo.py`, add this static method just above `get_available_items_per_user` (`app/TooGoodToGo.py:260`):

```python
    NOTIFICATION_TYPES = ("sold_out", "new_stock", "stock_reduced", "stock_increased")

    @staticmethod
    def _user_needs_notifications(settings):
        if not settings:
            return False
        return any(settings.get(k, 0) for k in TooGoodToGo.NOTIFICATION_TYPES)
```

- [ ] **Step 4: Gate the loop on active users**

In `get_available_items_per_user`, replace the user-selection block (`app/TooGoodToGo.py:273-277`) — the comment plus `user_keys = list(users_login_data.keys())` plus `random.shuffle(user_keys)` — with:

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

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_logic.py::test_user_needs_notifications -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/TooGoodToGo.py tests/test_logic.py
git commit -m "feat: smart polling skips users with no active notifications"
```

---

### Task 6: Datadome/captcha block backoff in the poll loop

**Files:**
- Modify: `app/TooGoodToGo.py` (`get_available_items_per_user` per-user `except`)

**Why:** When TGTG's Datadome blocks an IP it surfaces as a captcha error. Hammering through it makes things worse. On a captcha block during polling, back off for 5 minutes before continuing, mirroring upstream's behavior.

- [ ] **Step 1: Add captcha-aware backoff to the per-user error handler**

In `get_available_items_per_user`, the per-user `except Exception as e:` block currently (`app/TooGoodToGo.py:340-350`) logs, increments `consecutive_errors`, breaks on the max, and `continue`s. Replace that block with:

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

- [ ] **Step 2: Run the suite**

Run: `python -m pytest tests/ -v`
Expected: PASS (no new unit test; this path needs a live captcha to exercise).

- [ ] **Step 3: Commit**

```bash
git add app/TooGoodToGo.py
git commit -m "feat: back off 5 minutes on captcha/Datadome block during polling"
```

---

### Task 7: Harden message formatting against API shape changes

**Files:**
- Modify: `app/TooGoodToGo.py` (`format_message` → static, guarded)
- Test: `tests/test_logic.py`

**Why:** `format_message` (`app/TooGoodToGo.py:202-239`) indexes deeply nested keys (`item['item']['price_including_taxes']['minor_units']`) with no guards. A single item missing a field raises `KeyError`, which in the poll loop aborts the whole user's cycle. Making it a tolerant `@staticmethod` also makes it unit-testable.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_logic.py`:

```python
def test_format_message_handles_missing_optional_fields():
    import TooGoodToGo
    item = {
        "items_available": 3,
        "item": {"item_id": "i1", "price_including_taxes": {"minor_units": 499}},
        "store": {"store_id": "s1", "store_name": "Bakery",
                  "store_location": {"address": {"address_line": "1 Main St"}}},
        # no pickup_interval
    }
    message, item_id, store_id, store_name = TooGoodToGo.TooGoodToGo.format_message(item, "new_stock")
    assert item_id == "i1" and store_id == "s1" and store_name == "Bakery"
    assert "€4.99" in message and "3 bags available" in message
    assert message.startswith("*NEW BAGS AVAILABLE*")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_logic.py::test_format_message_handles_missing_optional_fields -v`
Expected: FAIL — currently an instance method (called unbound it's missing `self`), and key access assumptions differ.

- [ ] **Step 3: Replace `format_message` with a guarded static method**

Replace `app/TooGoodToGo.py:202-239` with:

```python
    @staticmethod
    def format_message(item, status=None):
        store = item.get('store', {})
        store_name = store.get('store_name', 'Unknown store')
        store_id = store.get('store_id', '')
        address = store.get('store_location', {}).get('address', {}).get('address_line', '')
        inner = item.get('item', {})
        item_id = inner.get('item_id', '')
        minor_units = inner.get('price_including_taxes', {}).get('minor_units', 0)
        price = minor_units / 100
        items_available = item.get('items_available', 0)

        pickup_time = ""
        interval = item.get('pickup_interval')
        if interval and interval.get('start') and interval.get('end'):
            try:
                start_time = datetime.strptime(interval['start'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
                end_time = datetime.strptime(interval['end'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone()
                today = date.today()
                tomorrow = today + timedelta(days=1)
                if start_time.date() == today:
                    day_str = "Today"
                elif start_time.date() == tomorrow:
                    day_str = "Tomorrow"
                else:
                    day_str = start_time.strftime("%A")
                pickup_time = f"⏰ {day_str} {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')} ({start_time.strftime('%A')})"
            except (ValueError, KeyError):
                pickup_time = ""

        status_headers = {
            'new_stock': '*NEW BAGS AVAILABLE* 🛍️\n\n',
            'sold_out': '*SOLD-OUT* 🥺\n\n',
            'stock_increased': '*STOCK INCREASED* 📈\n\n',
            'stock_reduced': '*STOCK REDUCED* 📉\n\n',
        }
        message = status_headers.get(status, '')
        message += f"🏪 *{store_name}*\n"
        message += f"📍 {address}\n"
        message += f"💰 €{price:.2f}\n"
        message += f"🥡 {items_available} bags available\n"
        if pickup_time:
            message += f"{pickup_time}\n"
        return message, item_id, store_id, store_name
```

Calls remain `self.format_message(item, status)` / `self.format_message(item)` — calling a static method via `self` is valid, so the call sites in `send_available_favourite_items_for_one_user` and `get_available_items_per_user` need no change.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_logic.py::test_format_message_handles_missing_optional_fields -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/TooGoodToGo.py tests/test_logic.py
git commit -m "fix: tolerate missing fields in item formatting"
```

---

### Task 8: Prune unbounded `available_items_favorites` growth

**Files:**
- Modify: `app/TooGoodToGo.py` (add `_prune_seen_items`; apply before save)
- Test: `tests/test_logic.py`

**Why:** `available_items_favorites` accumulates every item ever seen and is never trimmed (`save_available_items_favorites`). Over time the table grows without bound. Keep only items still present among this cycle's seen IDs.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_logic.py`:

```python
def test_prune_seen_items_keeps_only_active():
    import TooGoodToGo
    seen = {"a": {"items_available": 1}, "b": {"items_available": 0}, "c": {"items_available": 2}}
    pruned = TooGoodToGo.TooGoodToGo._prune_seen_items(seen, active_ids={"a", "c"})
    assert set(pruned.keys()) == {"a", "c"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_logic.py::test_prune_seen_items_keeps_only_active -v`
Expected: FAIL with `AttributeError: ... '_prune_seen_items'`.

- [ ] **Step 3: Add the static helper**

In `app/TooGoodToGo.py`, add just below `_user_needs_notifications`:

```python
    @staticmethod
    def _prune_seen_items(seen, active_ids):
        return {item_id: data for item_id, data in seen.items() if item_id in active_ids}
```

- [ ] **Step 4: Track active IDs and prune before saving in the loop**

In `get_available_items_per_user`: initialise an accumulator at the top of the `try` (right after `temp_available_items = {}` at `app/TooGoodToGo.py:271`):

```python
                active_item_ids = set()
```

Record each item's id when processed — immediately after `store_id = item['store']['store_id']` inside the item loop (`app/TooGoodToGo.py:298`), add:

```python
                            active_item_ids.add(item_id)
```

Then replace the save call `self.db.save_available_items_favorites(available_items_favorites)` (`app/TooGoodToGo.py:353`) with:

```python
                if active_item_ids:
                    available_items_favorites = self._prune_seen_items(available_items_favorites, active_item_ids)
                self.db.save_available_items_favorites(available_items_favorites)
```

(Guarding on `active_item_ids` avoids wiping the table on a cycle that polled nobody — e.g. the Task 5 smart-poll skip.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_logic.py::test_prune_seen_items_keeps_only_active -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/TooGoodToGo.py tests/test_logic.py
git commit -m "fix: prune stale entries from available_items_favorites"
```

---

### Task 9: Remove leftover debug and dead code

**Files:**
- Modify: `app/database.py:171`
- Modify: `app/TooGoodToGo.py` (`is_group_chat`)

**Why:** `database.py:171` prints on every admin check; `is_group_chat` always returns `False` (leftover from the removed group feature). Confirm `is_group_chat` is unreferenced before deleting.

- [ ] **Step 1: Confirm `is_group_chat` is unused**

Run: `grep -rn "is_group_chat" app/`
Expected: only the definition in `app/TooGoodToGo.py:561-562`. If any caller exists, leave the method and skip Step 3.

- [ ] **Step 2: Remove the stray print in database.py**

In `app/database.py` `is_admin` (`app/database.py:166-172`), delete the line:

```python
        print(f"Database admin check for user {user_id_str}: {result}")  # Add this line for debugging
```

so the method reads:

```python
    def is_admin(self, user_id):
        self._connect()
        user_id_str = str(user_id)
        self._local.cursor.execute('SELECT 1 FROM admin_users WHERE user_id = ?', (user_id_str,))
        return bool(self._local.cursor.fetchone())
```

- [ ] **Step 3: Remove the dead `is_group_chat` method**

In `app/TooGoodToGo.py`, delete the method (`app/TooGoodToGo.py:561-562`):

```python
    def is_group_chat(self, chat_id):
        return False  # No more group chat functionality
```

- [ ] **Step 4: Verify nothing broke**

Run: `grep -rn "is_group_chat" app/ ; python -m pytest tests/ -v`
Expected: no `is_group_chat` references remain; all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/database.py app/TooGoodToGo.py
git commit -m "chore: remove debug print and dead is_group_chat method"
```

---

## Final verification

- [ ] **Run the whole suite**

Run: `python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Full manual smoke test**

Run the bot (`cd app && python main.py`). Verify: `/login` → `/pin` completes; `/info` lists items; `/settings` toggles persist; `/blacklist` add/remove works; the background poll fires a notification when a favourite restocks; `Ctrl+C` shuts down cleanly via the signal handlers in `app/main.py`.

---

## Self-Review Notes

- **Spec coverage:** Every item from the assessment is mapped — version bump (T2), PIN login (T3), per-user clients + 401 fix (T4), smart polling (T5), captcha backoff (T6), parsing guards (T7), unbounded growth (T8), debug/dead code (T9), tests throughout (T1 + per-task).
- **Type/name consistency:** `_credentials_from_client`, `_build_client`, `get_favourite_items(user_id, client)`, `_user_needs_notifications(settings)`, `_prune_seen_items(seen, active_ids)`, `message_queue_text`, `pending_logins`, `NOTIFICATION_TYPES` are defined once and used with matching signatures. The message queue carries both 2-tuples (text) and 5-tuples (link), dispatched by length in `process_message_queue`.
- **Known constraint:** Login, captcha backoff, and the 401-refresh round-trip require live TGTG calls, so they have manual verification steps rather than unit tests; pure logic is unit-tested.
