# Round-2 review — verification evidence

All commands run via `uv` from the repo root
`/Users/leeguanfeng/Documents/Github/radio-giveaway-notifier` on branch `main`.
The reviewer does not need to re-run anything; the exact outputs are recorded
below.

## 1. `uv run ruff check .`

```
All checks passed!
```

Result: **clean** (exit 0).

## 2. `uv run ruff format --check .`

```
26 files already formatted
```

Result: **clean** (exit 0).

## 3. `uv run pytest`

Summary line:

```
============================== 58 passed in 0.08s ==============================
```

Total: **58 passed, 0 failed** (exit 0). Baseline before this revision was 48;
the 10 new tests are the sitemap source suite (`tests/test_sitemap.py`, 8 tests)
and the two new CLI `--db` dedupe tests in `tests/test_cli.py`.

## 4. Fresh-db dedupe demo

Commands run in sequence:

```
rm -f /tmp/demo.db && uv run python -m hotline once --dry-run --db /tmp/demo.db
uv run python -m hotline once --dry-run --db /tmp/demo.db
uv run python -m hotline once --dry-run
```

### RUN 1 — fresh db (`--db /tmp/demo.db`)

```
🎵 Giveaway alert
Title: 987FM Contest: Win Tickets to the Show
URL: file:///Users/leeguanfeng/Documents/Github/radio-giveaway-notifier/fixtures/contest_page.html
Source: web
Score: 1.00
Matched: call now, first caller, phone lines, giveaway, contest, win, tickets
🎵 Giveaway alert
Title: 987FM Giveaway: Text In to Enter
URL: file:///Users/leeguanfeng/Documents/Github/radio-giveaway-notifier/fixtures/giveaway_page.html
Source: web
Score: 1.00
Matched: text in, giveaway, contest, whatsapp
🎵 Giveaway alert
Title: Audio window 0
URL: fixtures/transcript.txt#t=0
Source: audio
Score: 1.00
Matched: call now, phone lines, win, tickets
Done: 3 detection(s) notified.
exit=0
```

→ **3 detections**, exit 0.

### RUN 2 — immediate second run, same db

```
Done: 0 detection(s) notified.
exit=0
```

→ **0 detections** (sqlite 7-day dedupe), exit 0.

### RUN 3 — plain `--dry-run`, no `--db`

```
🎵 Giveaway alert
Title: 987FM Contest: Win Tickets to the Show
URL: file:///Users/leeguanfeng/Documents/Github/radio-giveaway-notifier/fixtures/contest_page.html
Source: web
Score: 1.00
Matched: call now, first caller, phone lines, giveaway, contest, win, tickets
🎵 Giveaway alert
Title: 987FM Giveaway: Text In to Enter
URL: file:///Users/leeguanfeng/Documents/Github/radio-giveaway-notifier/fixtures/giveaway_page.html
Source: web
Score: 1.00
Matched: text in, giveaway, contest, whatsapp
🎵 Giveaway alert
Title: Audio window 0
URL: fixtures/transcript.txt#t=0
Source: audio
Score: 1.00
Matched: call now, phone lines, win, tickets
Done: 3 detection(s) notified.
exit=0
```

→ **3 detections** (in-memory store, repeatable), exit 0.

## 5. `make install` does not install torch

The `install:` Makefile target:

```
install:
	uv venv
	uv sync --extra dev
```

Evidence that the `dev` extra pulls no audio deps:

```
$ uv sync --extra dev 2>&1 | grep -iE 'torch|faster-whisper' || echo "NO torch/faster-whisper pulled by --extra dev"
NO torch/faster-whisper pulled by --extra dev
```

`faster-whisper`/`torch` live only under the opt-in `audio` extra
(`make install-audio`). `make install` does **not** install torch.

## 6. `uv lock --check`

```
Resolved 31 packages in 4ms
```

Result: **in sync** (exit 0). No dependency changes were needed — the sitemap
source uses only stdlib (`xml.etree`, `re`, `urllib`), so `uv.lock` was left
untouched.

## CI note (review item 4)

`.github/workflows/ci.yml` already uses
`uv sync --python 3.13 --extra dev` and relies on the committed
`.python-version` (`3.13`). There is no `uv python pin` step, so CI does not
mutate tracked files.

## git log and status

```
$ git log --oneline -n 5
d54032c (HEAD -> main) feat: sitemap source + --db flag + 987FM docs (round-2 review)
00fcbce chore: mark hotline build task completed; record approved review
e7e1a21 fix: source resilience, dev-only install, pin python 3.13
8c59a8b fix: keep dry-run dedupe state in-memory so offline demo is repeatable
7830766 feat: cli wiring, docs, Makefile, CI
```

```
$ git status
On branch main
Your branch is ahead of 'origin/main' by 7 commits.
  (use "git push" to publish your local commits)
nothing to commit, working tree clean
```

Working tree is **clean**. Not pushed, no PR opened (per instructions).
