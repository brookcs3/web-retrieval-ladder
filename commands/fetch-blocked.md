---
description: Fetch a URL past a 403/418/Turnstile/429 wall by walking the retrieval ladder (browser-UA curl, keyed jina reader, archive.org go-around, stealth handoff)
argument-hint: <url> [what to extract]
---

Fetch this past the wall: $ARGUMENTS

Follow the `fetching-blocked-urls` skill: escalate only on a real wall, one
rung per step, one variable per retry, read the STATUS line before deciding,
never narrate cooldowns, never print the key.

Script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ladder.py"` (development
checkout: `/path/to/web-retrieval-ladder/scripts/ladder.py`).

1. Rung 0 check. If the URL is ordinary open web and no wall signal has been
   seen yet, use WebFetch first and stop there if it works. This command
   exists for walls.
2. Run `ladder.py fetch <url>`. It walks rung 1 (browser-UA curl with `-L`)
   then rung 2 (the keyed `r.jina.ai` reader with `X-Engine: browser`,
   `X-No-Cache: true`, `X-Token-Budget: 120000`, 4 tries, `4 + 3*i` s backoff)
   and prints one STATUS line (`# STATUS: <verdict> | rung=N | <diagnosis;
   next move>`, always the first stdout line; per-try traces go to stderr),
   then the unwrapped body. For a big page add `--selector "<css>"` or
   `--max-chars N`; `--out FILE` writes the body to a file.
3. Act on the STATUS line, one variable per retry:
   - `ok`: check the `Title:` and body before trusting it. An `Error | <site>`
     title, "Access Denied", a login form, or a suspiciously short body is a
     soft block: go to step 5.
   - `EMPTY-RAW` or `PARSE-FAIL`: run `ladder.py diagnose <url>` once, read
     each rung's first 200 bytes, change the one variable it names, run
     `fetch` once more.
   - `CHALLENGE`: one more `fetch` (the proxy is stochastic). Still
     CHALLENGE: step 5.
   - `BUDGET`: shrink the request (a field-filtered URL such as
     `&at=results,pagination`, or a CSS selector through `X-Target-Selector`);
     never raise the budget.
   - `KEY-402`: a 402 (balance spent) or a 401 (key not sent or rejected).
     Run `ladder.py health`, report the balance, flag the top-up or fix the
     key. Do not keep calling the reader.
   - `RATE-429` on archive.org: run `ladder.py wayback <url> [--grep tok1,tok2]`,
     which routes the availability call through the reader and pulls-and-greps
     any capture (a snapshot's existence is never the verdict; its content
     is). On other origins: back off seconds, not minutes, single calls; if the
     page is on a known stealth-tier ground, step 5.
   - `TIMEOUT`: one more `fetch`. If the body literally says the service is
     offline, report that verbatim.
4. If a specific extraction was requested after the URL, answer that from the
   body instead of dumping the page. Otherwise say what the page contains and
   where the body was saved.
5. Escalation handoff, only for a genuine Turnstile / PerimeterX / managed
   challenge or a known stealth-tier ground (the Veridian archives,
   NewspaperArchive, amlegal, britannica; UDN's 418 is passed by rung 2, so
   it is not one): run `/stealth-fetch <url>` from the `seleniumbase-stealth`
   plugin (its MCP tools are `stealth_fetch`, then `cdp_fetch`, then the
   `session_*` set), warning first that the mouse cursor will move. Never
   route an ordinary lookup there.
6. If every rung fails, say so plainly and list exactly what was tried (rung,
   variable changed, STATUS). Do not loop, and do not claim "blocked" unless
   a response literally said so.
