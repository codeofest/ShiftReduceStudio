"""
app.py - Flask backend for ShiftReduce Studio
Run with:  python app.py   then open http://127.0.0.1:5000
"""
import csv
import hashlib
import io
import os
import threading
import time
import webbrowser

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from grammar import Grammar, GrammarError, InputError, tokenize
from sr_parser import ShiftReduceParser

app = Flask(__name__)
LOCK = threading.Lock()
MAX_INPUT_CHARS, MAX_TOKENS, MAX_HISTORY = 2000, 500, 50

# In-memory application state (reset when the server restarts or via /api/reset)
STATE = {"grammars": set(), "accepted": 0, "rejected": 0, "history": [], "next_id": 1}

SAMPLES = [
    {"id": "arithmetic", "name": "Arithmetic expressions", "start": "E", "input": "id+id*id",
     "grammar": "E -> E + T | T\nT -> T * F | F\nF -> ( E ) | id"},
    {"id": "anbn", "name": "Simple expressions (aⁿbⁿ)", "start": "S", "input": "aaabbb",
     "grammar": "S -> aSb | ab"},
    {"id": "basic", "name": "Basic grammar", "start": "S", "input": "ab",
     "grammar": "S -> aA\nA -> b"},
    {"id": "epsilon", "name": "Epsilon productions", "start": "S", "input": "aab",
     "grammar": "S -> A B\nA -> a A | ε\nB -> b"},
    {"id": "parens", "name": "Balanced parentheses (ε)", "start": "S", "input": "(()())",
     "grammar": "S -> ( S ) S | ε"},
    {"id": "ambiguous", "name": "Ambiguous grammar (conflicts)", "start": "E", "input": "id+id*id",
     "grammar": "E -> E + E | E * E | id"},
]


# ----------------------------------------------------------------- helpers
def fail(message, code=400, **extra):
    return jsonify(dict(ok=False, error=message, **extra)), code


def build(data):
    """Create Grammar + ShiftReduceParser from the JSON body (raises GrammarError)."""
    text = str(data.get("grammar", ""))
    if not text.strip():
        raise GrammarError([{"line": None, "text": "", "message": "The grammar is empty. Enter at least one production."}])
    g = Grammar.from_text(text, str(data.get("start", "")))
    return g, ShiftReduceParser(g, str(data.get("policy", "shift")))


def analysis(g, p):
    d = g.to_dict()
    d.update(table=p.table_view(), conflicts=p.conflicts, slr1=not p.conflicts,
             states=len(p.states), policy=p.policy)
    return d


def stats():
    return {"grammars": len(STATE["grammars"]), "accepted": STATE["accepted"],
            "rejected": STATE["rejected"], "total": STATE["accepted"] + STATE["rejected"]}


def page(template, key):
    return render_template(template, page=key)


# ------------------------------------------------------------------- pages
@app.route("/")
def index():
    return page("index.html", "dashboard")


@app.route("/simulator")
def simulator():
    return page("simulator.html", "simulator")


@app.route("/algorithm")
def algorithm():
    return page("algorithm.html", "algorithm")


@app.route("/history")
def history_page():
    return page("history.html", "history")


@app.route("/about")
def about():
    return page("about.html", "about")


# --------------------------------------------------------------------- API
@app.route("/api/samples")
def api_samples():
    return jsonify(ok=True, samples=SAMPLES)


@app.route("/api/stats")
def api_stats():
    with LOCK:
        return jsonify(ok=True, **stats())


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """Grammar validation + analysis only. No string is parsed here."""
    data = request.get_json(silent=True) or {}
    try:
        g, p = build(data)
    except GrammarError as e:
        return fail("Invalid grammar.", type="grammar", errors=e.errors)
    return jsonify(ok=True, analysis=analysis(g, p))


@app.route("/api/parse", methods=["POST"])
def api_parse():
    data = request.get_json(silent=True) or {}
    text = str(data.get("input", ""))
    try:
        g, p = build(data)
    except GrammarError as e:
        return fail("Invalid grammar.", type="grammar", errors=e.errors)
    if not text.strip():
        return fail("The input string is empty. Type a string such as id+id (type ε to parse the empty string).", type="input")
    if len(text) > MAX_INPUT_CHARS:
        return fail("The input string is too long (limit %d characters)." % MAX_INPUT_CHARS, type="input")
    try:
        tokens = tokenize(text, g.terminals)
    except InputError as e:
        return fail(str(e), type="input", unknown=e.unknown)
    if len(tokens) > MAX_TOKENS:
        return fail("The input has too many tokens (limit %d)." % MAX_TOKENS, type="input")

    result = p.parse(tokens)
    key = hashlib.md5(("\n".join(l.strip() for l in str(data.get("grammar", "")).splitlines() if l.strip())
                       + "|" + g.start).encode("utf-8")).hexdigest()
    with LOCK:
        STATE["grammars"].add(key)
        STATE["accepted" if result["accepted"] else "rejected"] += 1
        hid = STATE["next_id"]
        STATE["next_id"] += 1
        STATE["history"].insert(0, {
            "id": hid, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "grammar": str(data.get("grammar", "")),
            "start": g.start, "input": text, "policy": p.policy, "accepted": result["accepted"],
            "message": result["message"], "steps": result["steps"]})
        del STATE["history"][MAX_HISTORY:]
        snapshot = stats()
    return jsonify(ok=True, accepted=result["accepted"], message=result["message"], tokens=tokens,
                   steps=result["steps"], tree=result["tree"], analysis=analysis(g, p),
                   history_id=hid, stats=snapshot)


@app.route("/api/history")
def api_history():
    with LOCK:
        rows = [{k: h[k] for k in ("id", "time", "grammar", "start", "input", "policy", "accepted", "message")}
                | {"steps": len(h["steps"])} for h in STATE["history"]]
    return jsonify(ok=True, history=rows)


@app.route("/api/history/<int:hid>/csv")
def api_history_csv(hid):
    with LOCK:
        entry = next((h for h in STATE["history"] if h["id"] == hid), None)
    if entry is None:
        return fail("That parsing run is no longer in the history.", 404)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Step", "Stack", "Remaining Input", "Action", "Explanation"])
    for s in entry["steps"]:
        w.writerow([s["step"], " ".join(s["stack"]), " ".join(s["input"]), s["detail"], s["explanation"]])
    # BOM so that Excel on Windows shows ε, • and → correctly
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=parsing_steps_%d.csv" % hid})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    with LOCK:
        STATE.update(grammars=set(), accepted=0, rejected=0, history=[])
        return jsonify(ok=True, **stats())


@app.errorhandler(Exception)
def on_error(e):
    """Never show a Python traceback to the user."""
    if isinstance(e, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error=e.description), e.code
        return e
    app.logger.exception(e)
    return jsonify(ok=False, error="Internal error: %s" % e), 500


if __name__ == "__main__":
    host, port = "127.0.0.1", 5000
    url = "http://%s:%d" % (host, port)
    print("\n  ShiftReduce Studio is running at %s  (press Ctrl+C to stop)\n" % url)
    if os.environ.get("SRS_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False)
