#!/usr/bin/env python3
"""Payload harness for hooks/wall_detect.py: 54 stdin payloads, fire/no-fire expectations, runtime.

Usage: python3 hooks/test_wall_detect.py [--show] [path/to/wall_detect.py]
Exit 0 when every case passes. Each case must finish under 0.3 s.
"""
import json, os, subprocess, sys, time
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SCRIPT = ARGS[0] if ARGS else os.path.join(os.path.dirname(os.path.abspath(__file__)), "wall_detect.py")
PY = sys.executable

def base(event, tool, tool_input, **extra):
    d = {"session_id": "t", "transcript_path": "/tmp/t.jsonl", "cwd": "/tmp", "permission_mode": "default",
         "hook_event_name": event, "tool_name": tool, "tool_input": tool_input, "tool_use_id": "toolu_t"}
    d.update(extra); return d

def bash(cmd, stdout, stderr=""):
    return base("PostToolUse", "Bash", {"command": cmd, "description": "x"},
                tool_response={"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False, "noOutputExpected": False})

def webfetch(url, code, codeText, result, nbytes=0):
    return base("PostToolUse", "WebFetch", {"url": url, "prompt": "read"},
                tool_response={"bytes": nbytes, "code": code, "codeText": codeText, "result": result, "durationMs": 1234, "url": url})

def failure(tool, tool_input, error):
    return base("PostToolUseFailure", tool, tool_input, error=error, is_interrupt=False)

HMDB = "https://www.hmdb.org/m.asp?m=1"
CF_1P2K = ('<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>'
  '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><meta name="robots" content="noindex,nofollow">'
  '<meta name="viewport" content="width=device-width,initial-scale=1"><style>*{box-sizing:border-box;margin:0;padding:0}'
  'html{line-height:1.15;color:#313131;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}</style></head>'
  '<body class="no-js"><div class="main-wrapper" role="main"><div class="main-content"><noscript><div class="h2">'
  '<span id="challenge-error-text">Enable JavaScript and cookies to continue</span></div></noscript>'
  '<h1 class="zone-name-title h1">www.hmdb.org</h1><p id="cf-spinner-please-wait">Verifying you are human. This may take a few seconds.</p>'
  '<div id="challenge-stage"><div class="cf-turnstile" data-sitekey="0x4AAAAAAADnPIDROrmt1Wwj"></div></div>'
  '<div id="challenge-body-text" class="core-msg spacer">www.hmdb.org needs to review the security of your connection before proceeding.</div>'
  '</div></div><script>(function(){window._cf_chl_opt={cvId:\'3\',cZone:"www.hmdb.org",cType:\'managed\',cRay:\'8c7f1a2b3c4d5e6f\','
  'cUPMDTk:"/m.asp?m=1&__cf_chl_tk=xyz",cITimeS:\'1727200000\',cTplV:5};var a=document.createElement(\'script\');'
  'a.src=\'/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1?ray=8c7f1a2b3c4d5e6f\';document.getElementsByTagName(\'head\')[0].appendChild(a);}());'
  '</script><script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script></body></html>')
CF_WIDGET_ONLY = CF_1P2K.replace("<title>Just a moment...</title>", "<title>www.hmdb.org</title>").replace("Verifying you are human. This may take a few seconds.", "One moment please.").replace("Enable JavaScript and cookies to continue", "Please wait")

def big_html(size=40_000, inject_early="", inject_deep=""):
    head = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Venice Beach Historical Society: Marker Index</title><link rel="stylesheet" href="/static/css/site.css">'
            '<link rel="icon" href="/favicon.ico"><meta property="og:title" content="Marker Index"><script src="/static/js/app.js" defer></script></head>'
            '<body><header class="site-header"><nav class="nav"><a href="/">Home</a> <a href="/markers">Markers</a> <a href="/about">About</a> ')
    nav_tail = '<a href="/policies/access-denied-appeals">Access Denied</a> ' if inject_early == "anchor" else ""
    js_early = '<script>fetch("/api/markers").then(r=>r.json()).catch(e=>{throw new Error("Failed to fetch marker index")});</script>' if inject_early == "js" else ""
    head += nav_tail + '<a href="/contact">Contact</a></nav></header>' + js_early + '<main>'
    para = '<p>The marker stands at the corner of Windward Avenue and Ocean Front Walk, where the original arcade colonnade was dedicated in 1905. The inscription records the canal system, the Abbot Kinney Company, and the 1925 annexation to Los Angeles.</p>\n'
    body = ""
    while len(head) + len(body) < size - 2000:
        body += para
    deep = '<p>See also the <a href="/policies/access-denied-appeals">Access Denied</a> appeals page for research-room rules.</p>' if inject_deep == "anchor" else ""
    return head + body + deep + '</main><footer>Copyright 2026</footer></body></html>'

BIG_CLEAN = big_html()
assert len(BIG_CLEAN) > 38_000

CASES = [
 # name, payload(str or dict), expect_fire, must_contain_in_context(list), must_NOT_contain(list)
 ("01 WebFetch 403 dict (real shape)", webfetch(HMDB, 403, "Forbidden", "The server returned HTTP 403 Forbidden.\n\nThe response body was not retrieved. If this URL requires authentication, use an authenticated tool (e.g. `gh` for GitHub)."), True, ["403", HMDB, "fetching-blocked-urls", "ladder.py"], ["r.jina.ai/https"]),
 ("02 WebFetch 200 dict normal", webfetch("https://en.wikipedia.org/wiki/Venice,_Los_Angeles", 200, "OK", "Venice is a neighborhood of Los Angeles founded in 1905 by Abbot Kinney. The article covers the canals, the boardwalk and the 1925 annexation.", 96000), False, [], []),
 ("03 WebFetch tool_response as string 403", base("PostToolUse", "WebFetch", {"url": HMDB, "prompt": "x"}, tool_response="Request failed with status code 403"), True, ["403", HMDB], []),
 ("04 Bash curl -si HTTP/2 403", bash(f'curl -si "{HMDB}"', "HTTP/2 403 \r\ndate: Wed, 24 Sep 2026 20:00:00 GMT\r\ncontent-type: text/html; charset=UTF-8\r\nserver: cloudflare\r\ncf-mitigated: challenge\r\n\r\n" + CF_1P2K), True, ["403", HMDB], []),
 ("05 Bash curl -w http=%{http_code} (SKILL rung-1 format)", bash(f'UA="Mozilla/5.0"; curl -s -L --max-time 40 -A "$UA" -o /tmp/p.html -w "http=%{{http_code}} bytes=%{{size_download}} final=%{{url_effective}}\\n" "{HMDB}"', f"http=403 bytes=5923 final={HMDB}\n"), True, ["403", HMDB], []),
 ("06 Bash bare 403 from -w %{http_code}", bash(f"curl -s -o /dev/null -w '%{{http_code}}' {HMDB}", "403"), True, ["403"], []),
 ("07 Bash bare 200", bash(f"curl -s -o /dev/null -w '%{{http_code}}' {HMDB}", "200"), False, [], []),
 ("08 Bash ladder.py suppressed", bash(f'python3 "$L" diagnose "{HMDB}"', "# STATUS: CHALLENGE | rung=1 | http 403, signature Just a moment; next: rung 2\n# rung=2: ok"), False, [], []),
 ("09 Bash 1.2KB Cloudflare challenge body", bash(f'curl -s "{HMDB}"', CF_1P2K), True, ["Cloudflare", HMDB], []),
 ("10 Bash CF widget only (no title phrase, small)", bash(f'curl -s "{HMDB}"', CF_WIDGET_ONLY), True, ["turnstile"], []),
 ("11 Bash 40KB HTML, Access Denied in early <a> label", bash("curl -s https://venicehistorical.example.org/markers", big_html(inject_early="anchor")), False, [], []),
 ("12 Bash 40KB HTML, Access Denied in deep <a> label", bash("curl -s https://venicehistorical.example.org/markers", big_html(inject_deep="anchor")), False, [], []),
 ("13 Bash 40KB HTML, 'Failed to fetch' in early inline JS", bash("curl -s https://venicehistorical.example.org/markers", big_html(inject_early="js")), False, [], []),
 ("14 Bash Akamai Access Denied 400B page", bash("curl -s https://www.britannica.com/place/Venice-California", '<HTML><HEAD>\n<TITLE>Access Denied</TITLE>\n</HEAD><BODY>\n<H1>Access Denied</H1>\n \nYou don\'t have permission to access "http://www.britannica.com/place/Venice-California" on this server.<P>\nReference&#32;&#35;18&#46;4d0c1502&#46;1727200000&#46;1a2b3c4d\n</BODY>\n</HTML>\n'), True, ["Access Denied", "britannica"], []),
 ("15 Read tool with wall words (must not fire)", base("PostToolUse", "Read", {"file_path": "/tmp/notes.md"}, tool_response={"type": "text", "file": {"filePath": "/tmp/notes.md", "content": "HTTP/1.1 403 Forbidden\nJust a moment...\ncf-turnstile\nAccess Denied", "numLines": 4, "startLine": 1, "totalLines": 4}}), False, [], []),
 ("16 empty stdin", "", False, [], []),
 ("17 malformed JSON", "{not json", False, [], []),
 ("18 Bash reader URL challenge (strip r.jina.ai prefix)", bash(f'curl -s -H "Authorization: Bearer $JINA_API_KEY" -H "X-Engine: browser" "https://r.jina.ai/{HMDB}"', f"Title: Just a moment...\nURL Source: {HMDB}\n\nMarkdown Content:\nVerifying you are human. This may take a few seconds.\n"), True, [f'diagnose "{HMDB}"'], ["diagnose \"https://r.jina.ai", "diagnose https://r.jina.ai"]),
 ("19 Bash git push 403 (not a web wall)", bash("git push origin main", "", "remote: Permission to foo/bar.git denied to user.\nfatal: unable to access 'https://github.com/foo/bar.git/': The requested URL returned error: 403"), False, [], []),
 ("20 Bash archive.org 429 via curl -si", bash("curl -si 'http://archive.org/wayback/available?url=chroniclingamerica.loc.gov/lccn/sn89058318/1916-10-12/ed-1/seq-3/'", "HTTP/1.1 429 Too Many Requests\r\nServer: nginx\r\nContent-Type: text/html\r\n\r\n<html><head><title>429 Too Many Requests</title></head><body><h1>Too Many Requests</h1></body></html>"), True, ["429", "wayback"], []),
 ("21 PostToolUseFailure Bash curl -f exit 22", failure("Bash", {"command": f'curl -sf "{HMDB}"'}, "Exit code 22\ncurl: (22) The requested URL returned error: 403"), True, ["403", HMDB, "PostToolUseFailure"], []),
 ("22 PostToolUseFailure WebFetch", failure("WebFetch", {"url": HMDB, "prompt": "x"}, "Error: Request failed with status code 403"), True, ["403", HMDB, "PostToolUseFailure"], []),
 ("23 Bash UDN 418 bare", bash("curl -s -o /dev/null -w '%{http_code}' 'https://newspapers.lib.utah.edu/details?id=123'", "418"), True, ["418", "newspapers.lib.utah.edu"], []),
 ("24 Bash 200KB clean HTML (runtime)", bash("curl -s https://venicehistorical.example.org/all", big_html(200_000)), False, [], []),
 ("25 WebFetch 200 prose about 403 errors", webfetch("https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403", 200, "OK", "The HTTP 403 Forbidden response status code indicates that the server understood the request but refuses to authorize it. Unlike 401, re-authenticating makes no difference. Access Denied pages are a common presentation.", 40000), False, [], []),
 ("26 Bash curl -v 403 in stderr", bash(f'curl -v -o /dev/null "{HMDB}"', "", "* Connected to www.hmdb.org\n> GET /m.asp?m=1 HTTP/2\n< HTTP/2 403 \n< server: cloudflare\n"), True, ["403", HMDB], []),
 ("27 Bash python probe 'status: 403'", bash("python3 /tmp/probe.py", "url: https://www.loc.gov/collections/chronicling-america/?q=x&fo=json\nstatus: 403\nbytes: 5923"), True, ["403"], []),
 ("28 Bash npm 429 (registry, not a web wall)", bash("npm install left-pad", "", "npm ERR! code E429\nnpm ERR! 429 Too Many Requests - GET https://registry.npmjs.org/left-pad"), False, [], []),
 ("29 Bash Read-like large 200 loc.gov JSON w/ 'Just a moment' deep", bash("curl -s 'https://www.loc.gov/collections/chronicling-america/?q=brass+band&fo=json&at=results,pagination'", '{"pagination": {"of": 37}, "results": [' + ('{"title": "The Cotter Courier", "snippet": "brass band concert"}, ' * 900) + '{"title": "Just a moment ago the band"}]}'), False, [], []),
 ("30 WebFetch 200 but body is the CF interstitial summary", webfetch(HMDB, 200, "OK", "Just a moment... Verifying you are human. This may take a few seconds. www.hmdb.org needs to review the security of your connection before proceeding.", 1200), True, ["Cloudflare"], []),
 ("31 findagrave rung-1 success http=200", bash('curl -s -L -A "$UA" -o /tmp/p.html -w "http=%{http_code} bytes=%{size_download}\\n" "https://www.findagrave.com/memorial/1/"', "http=200 bytes=268076\n"), False, [], []),
 ("32 nginx <title>403 Forbidden</title> 170B", bash("curl -s https://example.org/x", "<html>\r\n<head><title>403 Forbidden</title></head>\r\n<body>\r\n<center><h1>403 Forbidden</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n"), True, [], []),
 ("33 reader Title: Error | Britannica (200)", bash('curl -s -H "Authorization: Bearer $JINA_API_KEY" "https://r.jina.ai/https://www.britannica.com/place/Venice-California"', "Title: Error | Britannica\n\nURL Source: https://www.britannica.com/place/Venice-California\n\nMarkdown Content:\nSomething went wrong.\n"), True, [], []),
 ("34 WebFetch 200 tiny Access Denied soft block", webfetch("https://www.britannica.com/place/Venice-California", 200, "OK", "Access Denied. You don't have permission to access this resource on this server.", 600), True, [], []),
 ("35 WebFetch 200 large page mentioning Access Denied", webfetch("https://x.example/policy", 200, "OK", "The policy page explains the Access Denied appeals process and the 403 Forbidden response.", 52000), False, [], []),
 ("36 WebFetch 503 Just a moment", webfetch(HMDB, 503, "Service Unavailable", "Just a moment... Checking your browser before accessing www.hmdb.org.", 3000), True, [], []),
 ("37 WebFetch 404 plain", webfetch("https://x.example/missing", 404, "Not Found", "The server returned HTTP 404 Not Found.", 0), False, [], []),
 ("38 gh api 403 rate limit (skipped family)", bash("gh api repos/foo/bar/issues", "", "HTTP 403: API rate limit exceeded for user ID 1 (https://docs.github.com/rest/overview/rate-limits-for-the-rest-api)"), False, [], []),
 ("39 git clone with URL, normal", bash("git clone https://github.com/foo/bar.git /tmp/bar", "", "Cloning into '/tmp/bar'...\n"), False, [], []),
 ("40 cd && python3 probe -> 403 line", bash("cd /tmp && python3 probe.py", "GET https://www.loc.gov/collections/chronicling-america/?fo=json\nstatus_code=403\n"), True, [], []),
 ("41 PostToolUseFailure is_interrupt", base("PostToolUseFailure", "Bash", {"command": f"curl -s {HMDB}"}, error="Just a moment...", is_interrupt=True), False, [], []),
 ("42 PostToolUseFailure is_timeout", base("PostToolUseFailure", "Bash", {"command": f"curl -s {HMDB}"}, error="Command timed out after 2m 0.0s", is_timeout=True), False, [], []),
 ("43 jina 422 data:null proxy error (not a wall)", bash(f'curl -s "https://r.jina.ai/{HMDB}"', '{"data":null,"code":422,"name":"AssertionFailureError","status":42206,"message":"No content available for URL"}'), False, [], []),
 ("44 jina 409 BudgetExceededError (not a wall)", bash(f'curl -s "https://r.jina.ai/{HMDB}"', '{"data":null,"code":409,"name":"BudgetExceededError","status":40903,"message":"Intended charge 7899 exceeds budget 3000"}'), False, [], []),
 ("45 jina 402 key exhausted (not a wall)", bash(f'curl -s "https://r.jina.ai/{HMDB}"', '{"data":null,"code":402,"name":"InsufficientBalanceError","status":40203,"message":"Insufficient balance"}'), False, [], []),
 ("46 ladder.py via $L variable, STATUS output", bash('python3 "$L" fetch "https://www.hmdb.org/m.asp?m=1"', "# STATUS: CHALLENGE | rung=2 | Just a moment via proxy; next: rung 5\n"), False, [], []),
 ("47 wall words in a command comment only", bash("# check for Access Denied\ncurl -s https://x.example/", "<html><head><title>Fine</title></head><body>" + "ok " * 2000 + "</body></html>"), False, [], []),
 ("48 tool_response as list of text blocks", base("PostToolUse", "WebFetch", {"url": HMDB, "prompt": "x"}, tool_response=[{"type": "text", "text": "Just a moment... Verify you are human"}]), True, [], []),
 ("49 PerimeterX block page", bash("curl -s https://www.newspaperarchive.com/x", '<html><head><title>Access to this page has been denied.</title></head><body><script src="https://client.px-cloud.net/PXabc123/main.min.js"></script><div id="px-captcha"></div><p>Please verify you are a human</p></body></html>'), True, [], []),
 ("50 DataDome block page", bash("curl -s https://www.example-shop.com/", '<html><head><title>example-shop.com</title><meta charset="utf-8"></head><body><div id="datadome-captcha"></div><script>var dd={"rt":"c","cid":"x","hsh":"y","t":"fe","s":1,"host":"geo.captcha-delivery.com"}</script><script src="https://ct.captcha-delivery.com/c.js"></script><p>DataDome</p></body></html>'), True, [], []),
 ("51 huge 200KB stdout with 'Just a moment' at byte 150000", bash("curl -s https://x.example/all", big_html(200_000).replace("</main>", "<p>Just a moment please</p></main>")), False, [], []),
 ("52 binary-ish stdout", bash("curl -s https://x.example/img.png", "\x89PNG\r\n\x1a\n" + "\x00\x01\x02\xff" * 5000), False, [], []),
 ("53 WebSearch tool (not scanned)", base("PostToolUse", "WebSearch", {"query": "403 Forbidden"}, tool_response={"result": "403 Forbidden Just a moment cf-turnstile"}), False, [], []),
 ("54 Bash JSON API 'status': 429 nested", bash("curl -s 'https://api.example.com/v1/x'", '{"error": {"status": 429, "message": "Rate limit exceeded"}}'), True, [], []),
 ("55 PostToolUseFailure Bash 'Error: Exit code 22' + bare 403", failure("Bash", {"command": f"curl -s -o /dev/null -w '%{{http_code}}\\n' '{HMDB}'; exit 22"}, "Error: Exit code 22\n403\n"), True, ["403", HMDB, "PostToolUseFailure"], []),
 ("56 PostToolUseFailure Bash exit 1 with clean 40KB html", failure("Bash", {"command": "curl -s https://venicehistorical.example.org/markers; exit 1"}, "Exit code 1\n" + big_html()), False, [], []),
]


def run(payload):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    env = dict(os.environ); env.pop("CLAUDE_PLUGIN_ROOT", None)
    t0 = time.perf_counter()
    p = subprocess.run([PY, SCRIPT], input=raw.encode(), capture_output=True, timeout=10, env=env)
    dt = time.perf_counter() - t0
    out = p.stdout.decode("utf-8", "replace")
    ctx = None
    if out.strip():
        try:
            ctx = json.loads(out)
        except Exception as e:
            ctx = {"_parse_error": str(e), "_raw": out[:200]}
    return p.returncode, dt, ctx, p.stderr.decode("utf-8", "replace")

rows = []; fails = 0; slow = 0
for name, payload, want_fire, must, must_not in CASES:
    rc, dt, ctx, err = run(payload)
    fired = ctx is not None
    ok = (rc == 0) and (fired == want_fire)
    text = json.dumps(ctx) if ctx else ""
    if fired and ok:
        hso = ctx.get("hookSpecificOutput", {}) if isinstance(ctx, dict) else {}
        ac = hso.get("additionalContext", "")
        ev = hso.get("hookEventName", "")
        text = ev + " | " + ac
        for m in must:
            if m not in text:
                ok = False; err += f" [missing: {m!r}]"
        for m in must_not:
            if m in text:
                ok = False; err += f" [forbidden present: {m!r}]"
        if "captcha" in ac.lower() and "never" not in ac.lower() and "not" not in ac.lower():
            ok = False; err += " [mentions solving captcha]"
    if dt >= 0.3: slow += 1
    if not ok: fails += 1
    rows.append((name, want_fire, fired, rc, dt, ok, text[:150].replace("\n", " "), err.strip()[:120]))

print(f"{'case':58} {'want':5} {'got':5} {'rc':3} {'sec':6} {'ok':4}")
for r in rows:
    print(f"{r[0]:58} {str(r[1]):5} {str(r[2]):5} {r[3]:<3} {r[4]:.3f}  {'PASS' if r[5] else 'FAIL'}  {r[7]}")
print(f"\nSUMMARY: {len(rows)-fails}/{len(rows)} pass, {fails} fail, {slow} over 0.3s, max {max(r[4] for r in rows):.3f}s")
if "--show" in sys.argv:
    for r in rows:
        if r[2]: print(f"\n[{r[0]}]\n{r[6]}")
sys.exit(1 if fails else 0)
