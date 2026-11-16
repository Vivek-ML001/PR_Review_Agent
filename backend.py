import os, re, sys, json, operator, requests, subprocess, tempfile
from typing import TypedDict, Annotated
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain_groq import ChatGroq

load_dotenv()

MODEL = "openai/gpt-oss-120b"
llm = ChatGroq(model=MODEL, temperature=0)
GH_TOKEN = os.getenv("GITHUB_TOKEN")
MAX_FILES, MAX_CHARS = 4, 8000
DOCS = (".md", ".txt", ".rst")
ORDER = {"CRITICAL": 0, "MAJOR": 1, "MINOR": 2}
ICON = {"CRITICAL": "🔴", "MAJOR": "🟠", "MINOR": "🟡"}


# ---------- helpers ----------
def gh_headers(accept="application/vnd.github+json"):
    h = {"Accept": accept}
    if GH_TOKEN:
        h["Authorization"] = f"Bearer {GH_TOKEN}"
    return h

def parse_url(url):
    m = re.match(r"https://github.com/(.+?)/(.+?)/pull/(\d+)", url.strip())
    if not m:
        raise ValueError("Invalid PR URL. Format: https://github.com/owner/repo/pull/1")
    return m.groups()

def parse_diff(diff):
    """Returns {file: {line_no: code}} for ADDED lines only (new-file line numbers)."""
    out, cur, ln = {}, None, 0
    for l in diff.splitlines():
        if l.startswith("diff --git"):
            cur, ln = None, 0
        elif l.startswith("+++ "):
            cur = l[6:] if l.startswith("+++ b/") else None
            if cur:
                out.setdefault(cur, {})
        elif l.startswith("@@"):
            m = re.search(r"\+(\d+)", l)
            ln = int(m.group(1)) if m else 0
        elif cur is not None and ln:
            if l.startswith("+"):
                out[cur][ln] = l[1:]
                ln += 1
            elif l.startswith(("-", "\\")):
                pass
            else:
                ln += 1
    return out

def build_context(s):
    added = parse_diff(s["diff"])
    rows = []
    for f, d in added.items():
        for n, t in d.items():
            if len(t) > 3000:
                t = t[:3000] + " ...[LINE TRUNCATED: do not report syntax issues]"
            rows.append(f"{f}:{n}: {t}")
    lines, total = [], 0
    for row in rows:                       # poori line lo ya rok do, beech me mat kaato
        if total + len(row) > 12000:
            break
        lines.append(row)
        total += len(row) + 1
    changed = "\n".join(lines)
    full = "\n\n".join(f"=== {p} ===\n{c}" for p, c in s.get("files", {}).items())
    return changed, full

def ask_json(prompt):
    for attempt in range(2):
        txt = llm.invoke(prompt + "\n\nReturn ONLY valid JSON, no markdown fences.").content
        m = re.search(r"[\[{].*[\]}]", txt, re.S)
        try:
            if m:
                return json.loads(m.group(0), strict=False)
        except Exception:
            pass
        print(f"⚠️ JSON parse failed (try {attempt + 1}):", str(txt)[:200])
    return []

def sev(f):
    v = str(f.get("severity", "MINOR")).upper()
    return v if v in ORDER else "MINOR"


# ---------- state ----------
class S(TypedDict, total=False):
    pr_url: str
    diff: str
    files: dict
    findings: Annotated[list, operator.add]
    tests: dict
    lint: list
    final: str
    inline: list


# ---------- nodes ----------
def fetch(s):
    if s.get("diff"):                      # evaluation mode: diff already given
        return {}
    o, r, n = parse_url(s["pr_url"])
    base = f"https://api.github.com/repos/{o}/{r}"
    res = requests.get(f"{base}/pulls/{n}", headers=gh_headers("application/vnd.github.v3.diff"))
    if res.status_code != 200:
        raise Exception(f"GitHub error {res.status_code}: {res.text[:200]}")
    diff = res.text
    sha = requests.get(f"{base}/pulls/{n}", headers=gh_headers()).json()["head"]["sha"]
    files = {}
    for path in list(parse_diff(diff))[:MAX_FILES]:
        if path.endswith(DOCS):
            continue
        c = requests.get(f"{base}/contents/{path}", params={"ref": sha},
                         headers=gh_headers("application/vnd.github.raw"))
        if c.status_code == 200:
            files[path] = c.text[:MAX_CHARS]
    return {"diff": diff, "files": files}

def router(s):
    return {}

def route(s):
    files = re.findall(r"diff --git a/(\S+)", s["diff"])
    docs_only = all(f.endswith(DOCS) for f in files)
    return END if docs_only else ["security", "bug", "test"]

RULES = ("Report only issues in CHANGED LINES. Use FULL FILES only as context. "
         "Do not speculate. 'line' must be a line number taken from CHANGED LINES. "
         "CHANGED LINES are complete, but FULL FILES may be cut off after 8000 characters: "
         "never report syntax errors, unterminated strings or invalid JSON/code "
         "unless the problem is clearly visible inside CHANGED LINES themselves.")

FINDING_FMT = ('Return a JSON list (max 3 items). Each item: {"file": str, "line": int, '
               '"severity": "CRITICAL|MAJOR|MINOR", "title": str (max 10 words), '
               '"detail": str (1-2 sentences), '
               '"fix": str (corrected code line, only if the line is under 150 characters, else "")}. '
               'Return [] if nothing found.')

SECURITY_TASK = ("Find security issues: hardcoded secrets, SQL/shell/eval injection, "
                 "unsafe deserialization, logging sensitive data. "
                 "CRITICAL for secrets or exploitable code, MAJOR otherwise.")
BUG_TASK = ("Find real logic bugs: crashes, wrong results, off-by-one, missing checks, "
            "swallowed exceptions, mutable default args. Do NOT report secrets, unused "
            "imports or style. A missing None check counts only if the value is used "
            "unsafely in FULL FILES. MAJOR if it can crash or give wrong results, else MINOR.")

def make_worker(name, task):
    def worker(s):
        changed, full = build_context(s)
        prompt = (f"You are a {name}. {RULES}\n{task}\n{FINDING_FMT}\n\n"
                  f"CHANGED LINES (file:line: code):\n{changed}\n\nFULL FILES:\n{full}")
        items = ask_json(prompt)
        if isinstance(items, dict):
            items = [items]
        good = [dict(i, worker=name) for i in items if isinstance(i, dict) and i.get("title")]
        return {"findings": good}
    return worker

def test_writer(s):
    changed, full = build_context(s)
    prompt = ("You are a test engineer. Write 1-2 short pytest functions that verify the "
              "CORRECT or SECURE behaviour of CHANGED LINES. Never assert a hardcoded secret, "
              "never test that an import exists, do not import streamlit apps. "
              'Return a JSON object {"file": "tests/test_<name>.py", "code": "<python code>"}. '
              'If the changed lines are not Python code, or nothing is worth testing, '
              'return {"file": "", "code": ""}.\n\n'
              f"CHANGED LINES:\n{changed}\n\nFULL FILES:\n{full}")
    r = ask_json(prompt)
    return {"tests": r if isinstance(r, dict) else {}}

def sandbox(s):
    added = parse_diff(s["diff"])
    lint = []
    for path, code in s.get("files", {}).items():
        if not path.endswith(".py"):
            continue
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write(code)
            out = subprocess.run([sys.executable, "-m", "flake8", "--max-line-length=100", p],
                                 capture_output=True, text=True).stdout
        for l in out.splitlines():
            m = re.match(r".*?f\.py:(\d+):\d+: (\w+) (.*)", l)
            if m and m.group(2) != "W292" and int(m.group(1)) in added.get(path, {}):   # only changed lines
                lint.append({"file": path, "line": int(m.group(1)),
                             "code": m.group(2), "msg": m.group(3)})
    return {"lint": lint}

def reducer(s):
    added = parse_diff(s["diff"])
    raw = s.get("findings", [])

    items, dropped, seen = [], [], set()
    for f in sorted(raw, key=lambda x: ORDER[sev(x)]):
        try:
            ln = int(f.get("line"))
        except (TypeError, ValueError):
            dropped.append(f)
            continue
        if ln not in added.get(f.get("file"), {}):        # changed line nahi hai
            dropped.append(f)
            continue
        key = (f.get("file"), ln)
        if key in seen:
            continue
        seen.add(key)
        f["line"] = ln
        items.append(f)

    print(f"[reducer] raw={len(raw)} kept={len(items)} dropped={len(dropped)}")
    for f in dropped:
        print("   dropped:", f.get("file"), f.get("line"), f.get("title"))

    lint = s.get("lint", [])
    c = {k: sum(1 for f in items if sev(f) == k) for k in ORDER}
    out = [f"**{len(items)} finding(s)**: {c['CRITICAL']} critical, {c['MAJOR']} major, "
           f"{c['MINOR']} minor · {len(lint)} lint · {len(dropped)} unverified\n", "### Findings"]
    if not items:
        out.append("No issues found.")

    inline = []
    for f in items:
        sv = sev(f)
        icon = ICON[sv]
        out.append(f"- {icon} **{sv}** `{f.get('file')}:{f['line']}` "
                   f"({f.get('worker')}): **{f.get('title')}**. {f.get('detail', '')}")
        if f.get("fix"):
            out.append(f"\n```python\n{f['fix']}\n```\n")
        body = f"{icon} **{sv}**: {f.get('title')}\n\n{f.get('detail', '')}"
        if f.get("fix"):
            body += f"\n\n**Suggested fix:**\n```python\n{f['fix']}\n```"
        inline.append({"path": f["file"], "line": f["line"], "side": "RIGHT", "body": body})

    if dropped:
        out.append("\n### ⚠️ Unverified (not on a changed line, check manually)")
        for f in dropped:
            out.append(f"- {sev(f)} `{f.get('file')}:{f.get('line')}` "
                       f"({f.get('worker')}): {f.get('title')}. {f.get('detail', '')}")

    t = s.get("tests") or {}
    if t.get("code"):
        out.append(f"\n### 🧪 Generated Tests (`{t.get('file') or 'tests/'}`)")
        out.append(f"```python\n{t['code']}\n```")

    out.append("\n### 🧹 Lint")
    if lint:
        out += [f"- `{l['file']}:{l['line']}` {l['code']} {l['msg']}" for l in lint]
    else:
        out.append("No lint issues.")
    return {"final": "\n".join(out), "inline": inline}


# ---------- graph ----------
g = StateGraph(S)
g.add_node("fetch", fetch)
g.add_node("router", router)
g.add_node("security", make_worker("Security Reviewer", SECURITY_TASK))
g.add_node("bug", make_worker("Bug Reviewer", BUG_TASK))
g.add_node("test", test_writer)
g.add_node("sandbox", sandbox)
g.add_node("reducer", reducer)

g.add_edge(START, "fetch")
g.add_edge("fetch", "router")
g.add_conditional_edges("router", route, ["security", "bug", "test", END])
g.add_edge(["security", "bug", "test"], "sandbox")
g.add_edge("sandbox", "reducer")
g.add_edge("reducer", END)
app = g.compile()


# ---------- GitHub posting ----------
def post_comment(url, body):
    o, r, n = parse_url(url)
    res = requests.post(f"https://api.github.com/repos/{o}/{r}/issues/{n}/comments",
                        headers=gh_headers(),
                        json={"body": "## 🤖 PR Review Agent\n\n" + body})
    return res.status_code == 201, res.text

def post_review(url, body, inline):
    """Posts summary + line-by-line comments. Falls back to a normal comment."""
    o, r, n = parse_url(url)
    res = requests.post(f"https://api.github.com/repos/{o}/{r}/pulls/{n}/reviews",
                        headers=gh_headers(),
                        json={"body": "## 🤖 PR Review Agent\n\n" + body,
                              "event": "COMMENT", "comments": inline})
    if res.status_code == 200:
        return True
    return post_comment(url, body)[0]


# ---------- public functions ----------
def run_review(pr_url, post=False):
    res = app.invoke({"pr_url": pr_url, "findings": []})
    final = res.get("final")
    if not final:
        return None, None                  # docs-only PR
    posted = post_review(pr_url, final, res.get("inline", [])) if post else None
    return final, posted

def make_diff(path, code):
    lines = code.splitlines()
    body = "\n".join("+" + l for l in lines)
    return (f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n"
            f"+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}\n")

def review_code(path, code):
    """Used by evaluate.py: runs the full graph on a code string."""
    return app.invoke({"diff": make_diff(path, code), "files": {path: code}, "findings": []})


# ---------- terminal test ----------
if __name__ == "__main__":
    url = input("PR URL: ")
    review, posted = run_review(url, post=False)
    print(review or "Docs only PR, review skip")