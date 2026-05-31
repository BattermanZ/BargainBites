# Conversational login + invite fix — remaining work

Branch: `tgtg-019-migration`

## Context / goal
Make `/login`, `/relogin`, `/start`, and `/pin` work conversationally: when sent
bare, the bot prompts and waits for the value in the next plain message. One-shot
forms (`/login email`, `/start <token>`, `/pin 12345`) still work. Also fix the
broken invite that told users to send `/authorize <token>` (no such handler).

Design decisions already locked with the user:
- Keep both bare-prompt **and** one-shot forms.
- PIN step is conversational too (next plain msg = PIN); `/pin 12345` still works.
- Any `/command` mid-flow cancels the pending prompt and runs that command.
- Plain text is consumed **only** when a prompt is pending (safe in group chats).

## DONE (already edited in working tree — NOT yet committed)

### `app/TooGoodToGo.py`
- Added `import re`.
- `__init__`: added `self.awaiting_input = {}` (chat_id -> "email" | "relogin_email" | "token" | "pin").
- Added helpers: `set_awaiting`, `get_awaiting`, `clear_awaiting`, and static `_is_valid_email`.
- `_initiate_login`: now calls `set_awaiting(uid, "pin")` and prompts user to just
  send the PIN (no longer says `/pin 12345`).
- `complete_login_with_pin`: clears awaiting on success / no-pending; on bad PIN
  re-sets awaiting to `"pin"` so user can just resend the code. Messages updated.

### `app/Telegram.py`
- Replaced `import re` / `import configparser` with `import asyncio` (configparser
  was unused; asyncio now needed at module top).
- Added shared helpers inside `setup_bot`: `command_arg`, `submit_email`
  (with `relogin=` kwarg), `submit_pin`, `submit_token`.
- `/start`: bare -> prompts for token (sets awaiting "token"); `/start <tok>` one-shot;
  clears awaiting on entry; authorized users get the welcome.
- `/login`: bare -> prompts for email; one-shot still works; clears awaiting on entry.
- `/relogin`: same pattern, awaiting "relogin_email".
- `/pin`: now just `clear_awaiting` + `submit_pin(command_arg(...))`.
- `/info` logged-out prompt + `/help` text updated to describe the new flow.
- `/generate_token` invite message now sends `/start {token}` (was `/authorize {token}`).
- Added catch-all `handle_followup` (registered last, before `shutdown`):
  routes plain text to the pending flow; ignores text when nothing is pending;
  only allows the "token" flow before authorization.

Both files pass `python -m ast` syntax check.

## TODO (what's left)

1. **Manual sanity re-read** of `app/Telegram.py` to confirm handler order: the
   catch-all `@bot.message_handler(func=lambda m: True, content_types=['text'])`
   must be the LAST registered handler so command handlers win. (It is, but verify.)

2. **Add regression tests** in `tests/test_logic.py` following the existing style
   (construct a bare handler instance via `__new__`, no telebot). Cover the pure
   state logic:
   - `set_awaiting` / `get_awaiting` / `clear_awaiting` round-trip.
   - `_is_valid_email` accepts `a@b.co`, rejects `/info`, ``, `notanemail`.
   - Optionally a small routing test if the routing is refactored into a pure
     function (currently routing lives in the telebot closure `handle_followup`,
     which is hard to unit-test without a fake bot; consider extracting a pure
     `route_followup(kind, text) -> action` helper if we want it tested).

3. **Run the suite**: `PYTHONPATH=app venv/bin/python -m pytest -q` (was 19 green
   before this change; keep it green).

4. **Live smoke test** (cannot be automated here): with a real bot token,
   - `/login` (bare) -> bot asks for email -> send email -> PIN email arrives ->
     send PIN as plain text -> "You are now logged in".
   - `/login foo@bar.com` one-shot still works.
   - `/start` (unauthorized, bare) -> asks for token -> send token -> authorized.
   - `/start <token>` deep-link still works.
   - Sending `/info` mid-prompt cancels the prompt and runs `/info`.
   - Random chatter in a group with no pending prompt is ignored.

5. **Commit & push** (user said push earlier; confirm before pushing). Suggested
   commit, per AGENTS.md format (subject + bullet body, real newlines):
   - `feat(telegram): conversational login/start/pin flows + fix invite command`
   - bullets: bare commands now prompt and wait; one-shot forms retained; PIN
     step conversational; cancel-on-command via catch-all; `/authorize` invite
     replaced with `/start <token>`; help/info text updated.

6. **AGENTS.md**: still untracked (`git status` shows `?? AGENTS.md` normally).
   User asked to commit it — `git add AGENTS.md` and include in (or alongside)
   the commit.

7. **README**: already rewritten/committed (commit `2f4770f`). The PIN section
   says "send `/pin`" — consider a follow-up doc tweak to mention the new
   "just send the PIN / email when asked" behavior. Minor.

## Notes / risks
- `pyTelegramBotAPI` 4.25.0 `AsyncTeleBot` has **no** `register_next_step_handler`
  (sync-only), which is why we use the explicit `awaiting_input` state map + a
  catch-all handler instead.
- State is in-memory (`awaiting_input` dict). A bot restart mid-flow drops the
  pending prompt — acceptable (user just resends the command). `pending_logins`
  was already in-memory with the same property.
