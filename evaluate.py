import json, time
from backend import review_code

# (name, code, keywords). keywords=None means CLEAN code (no MAJOR/CRITICAL expected)
CASES = [
    ("hardcoded_key", 'import requests\n\nAPI_KEY = "sk-live-9f8a7b6c5d4e3f"\n\ndef get(url):\n    return requests.get(url, headers={"Authorization": API_KEY})\n',
     ["hardcode", "secret", "credential", "api key", "token"]),
    ("sql_injection", 'import sqlite3\n\ndef get_user(name):\n    conn = sqlite3.connect("app.db")\n    return conn.execute(f"SELECT * FROM users WHERE name = \'{name}\'").fetchall()\n',
     ["sql", "injection", "parameter"]),
    ("eval_input", 'def calc(expr):\n    return eval(expr)\n',
     ["eval", "code execution", "injection"]),
    ("shell_injection", 'import subprocess\n\ndef list_dir(path):\n    return subprocess.run(f"ls {path}", shell=True)\n',
     ["shell", "injection", "command"]),
    ("password_logged", 'import logging\n\ndef login(user, password):\n    logging.info(f"login {user} {password}")\n',
     ["password", "log", "sensitive", "credential"]),
    ("empty_list", 'def last_msg(messages):\n    return messages[-1]["content"]\n',
     ["empty", "indexerror", "index"]),
    ("div_zero", 'def avg(nums):\n    return sum(nums) / len(nums)\n',
     ["zero", "empty", "division"]),
    ("mutable_default", 'def add(item, items=[]):\n    items.append(item)\n    return items\n',
     ["mutable", "default"]),
    ("bare_except", 'def load(path):\n    try:\n        return open(path).read()\n    except:\n        pass\n',
     ["except", "swallow", "silent", "bare"]),
    ("off_by_one", 'def total(xs):\n    t = 0\n    for i in range(len(xs) + 1):\n        t += xs[i]\n    return t\n',
     ["off-by-one", "off by one", "index", "range", "out of"]),
    ("clean_add", 'def add(a: int, b: int) -> int:\n    return a + b\n', None),
    ("clean_env", 'import os\n\ndef get_key() -> str:\n    key = os.getenv("API_KEY")\n    if not key:\n        raise RuntimeError("API_KEY is not set")\n    return key\n', None),
]

def big(res):
    return [f for f in res.get("findings", [])
            if str(f.get("severity")).upper() in ("CRITICAL", "MAJOR")]

def caught(res, kws):
    for f in big(res):
        text = (str(f.get("title")) + " " + str(f.get("detail"))).lower()
        if any(k in text for k in kws):
            return True
    return False

rows, bug_hit, bug_total, fp, clean_total, times = [], 0, 0, 0, 0, []
for name, code, kws in CASES:
    t0 = time.time()
    try:
        res = review_code(f"{name}.py", code)
    except Exception as e:
        print(f"{name:18} ERROR {e}")
        continue
    dt = round(time.time() - t0, 1)
    times.append(dt)
    if kws:
        ok = caught(res, kws)
        bug_total += 1
        bug_hit += ok
        status = "✅ caught" if ok else "❌ missed"
    else:
        bad = len(big(res)) > 0
        clean_total += 1
        fp += bad
        status = "❌ false alarm" if bad else "✅ clean"
    rows.append({"case": name, "status": status, "findings": len(res.get("findings", [])), "sec": dt})
    print(f"{name:18} {status:15} findings={len(res.get('findings', []))}  {dt}s")
    time.sleep(20)   # Groq free rate limit se bachne ke liye

print("\n------ RESULT ------")
print(f"Bugs caught : {bug_hit}/{bug_total}  ({round(100 * bug_hit / max(bug_total, 1))}%)")
print(f"False alarms: {fp}/{clean_total} clean files")
print(f"Avg time    : {round(sum(times) / max(len(times), 1), 1)}s per review")
with open("eval_results.json", "w") as f:
    json.dump(rows, f, indent=2)