"""Automated tests:  python tests.py"""
import unittest

from app import app, STATE
from grammar import Grammar, GrammarError, InputError, tokenize
from sr_parser import ShiftReduceParser

ARITH = "E -> E + T | T\nT -> T * F | F\nF -> ( E ) | id"


def run(grammar, text, start="", policy="shift"):
    g = Grammar.from_text(grammar, start)
    p = ShiftReduceParser(g, policy)
    return g, p, p.parse(tokenize(text, g.terminals))


def leaves(node):
    if not node["children"]:
        return [] if node.get("epsilon") else [node["symbol"]]
    return [x for c in node["children"] for x in leaves(c)]


class Parsing(unittest.TestCase):
    def test_required_strings(self):
        for s, expected in [("id+id", True), ("id*id", True), ("id+id*id", True), ("(id+id)*id", True),
                            ("id+", False), ("+id", False), ("id*id+", False)]:
            with self.subTest(s=s):
                g, p, r = run(ARITH, s)
                self.assertEqual(r["accepted"], expected)
                self.assertEqual(r["steps"][-1]["action"], "ACCEPT" if expected else "ERROR")
                if expected:
                    self.assertEqual(leaves(r["tree"]), tokenize(s, g.terminals))
                else:
                    self.assertIsNone(r["tree"])

    def test_exact_trace(self):
        _, p, r = run(ARITH, "id+id")
        self.assertEqual([s["detail"] for s in r["steps"]], [
            "SHIFT", "REDUCE F -> id", "REDUCE T -> F", "REDUCE E -> T", "SHIFT", "SHIFT",
            "REDUCE F -> id", "REDUCE T -> F", "REDUCE E -> E + T", "ACCEPT"])
        self.assertEqual(r["steps"][0]["stack"], ["$"])
        self.assertEqual(r["steps"][0]["input"], ["id", "+", "id", "$"])
        self.assertEqual(r["steps"][4]["stack"], ["$", "E"])
        self.assertEqual(r["steps"][8]["stack"], ["$", "E", "+", "T"])

    def test_precedence_in_tree(self):
        _, _, r = run(ARITH, "id+id*id")
        self.assertEqual(r["tree"]["rule"], "E -> E + T")           # * binds tighter than +
        self.assertEqual(r["tree"]["children"][2]["rule"], "T -> T * F")

    def test_compact_grammars(self):
        self.assertTrue(run("S -> aSb | ab", "aaabbb")[2]["accepted"])
        self.assertFalse(run("S -> aSb | ab", "aabbb")[2]["accepted"])
        self.assertTrue(run("S -> aA\nA -> b", "ab")[2]["accepted"])
        self.assertFalse(run("S -> aA\nA -> b", "a")[2]["accepted"])

    def test_epsilon(self):
        g = "S -> A B\nA -> a A | ε\nB -> b"
        self.assertTrue(run(g, "aab")[2]["accepted"])
        self.assertTrue(run(g, "b")[2]["accepted"])
        self.assertFalse(run(g, "aa")[2]["accepted"])
        _, p, r = run(g, "b")
        self.assertIn("REDUCE A -> ε", [s["detail"] for s in r["steps"]])
        self.assertTrue(run("S -> ( S ) S | ε", "(()())")[2]["accepted"])
        self.assertFalse(run("S -> ( S ) S | ε", "(()")[2]["accepted"])
        self.assertTrue(run("S -> ( S ) S | ε", "ε")[2]["accepted"])      # empty string
        self.assertEqual(Grammar.from_text(g).to_dict()["nullable"], ["A"])

    def test_first_follow(self):
        d = Grammar.from_text(ARITH).to_dict()
        self.assertEqual(d["first"]["E"], ["(", "id"])
        self.assertEqual(d["follow"]["E"], ["+", ")", "$"])
        self.assertEqual(d["follow"]["F"], ["+", "*", ")", "$"])

    def test_conflicts(self):
        amb = "E -> E + E | E * E | id"
        _, p, r = run(amb, "id+id*id")
        self.assertTrue(p.conflicts)
        self.assertEqual(p.conflicts[0]["kind"], "shift/reduce")
        self.assertTrue(r["accepted"])
        self.assertTrue(any(s["conflict"] for s in r["steps"]))
        _, p2, r2 = run(amb, "id+id*id", policy="reduce")
        self.assertTrue(r2["accepted"])
        self.assertNotEqual(r["tree"]["rule"], r2["tree"]["rule"])        # different associativity/precedence
        self.assertFalse(run(ARITH, "id")[1].conflicts)

    def test_infinite_loop_guard(self):
        _, _, r = run("A -> B | a\nB -> A\nS -> A", "a", start="S")
        self.assertFalse(r["accepted"])
        self.assertIn("Infinite loop", r["message"])

    def test_unknown_terminal(self):
        with self.assertRaises(InputError):
            tokenize("id+x", Grammar.from_text(ARITH).terminals)

    def test_invalid_grammars(self):
        for bad in ["", "E E + T", "E -> | a", "-> a", "1x -> a", "| a", "E -> a ->", "E -> a $"]:
            with self.subTest(bad=bad), self.assertRaises(GrammarError):
                Grammar.from_text(bad)
        with self.assertRaises(GrammarError):
            Grammar.from_text(ARITH, "Q")
        w = Grammar.from_text("S -> A x\nB -> y").to_dict()["warnings"]
        self.assertTrue(any("missing production" in x for x in w))
        self.assertTrue(any("Unreachable" in x for x in w))


class Api(unittest.TestCase):
    def setUp(self):
        self.c = app.test_client()
        self.c.post("/api/reset")

    def post(self, url, **body):
        r = self.c.post(url, json=body)
        return r.status_code, r.get_json()

    def test_pages(self):
        for u in ["/", "/simulator", "/algorithm", "/history", "/about", "/api/samples", "/api/stats"]:
            self.assertEqual(self.c.get(u).status_code, 200, u)

    def test_parse_and_stats_and_csv(self):
        for s in ["id+id", "id+"]:
            code, d = self.post("/api/parse", grammar=ARITH, start="E", input=s)
            self.assertEqual(code, 200)
        st = self.c.get("/api/stats").get_json()
        self.assertEqual((st["grammars"], st["accepted"], st["rejected"]), (1, 1, 1))
        self.assertEqual(len(self.c.get("/api/history").get_json()["history"]), 2)
        csv = self.c.get("/api/history/%d/csv" % d["history_id"])
        self.assertEqual(csv.status_code, 200)
        self.assertIn("Step,Stack,Remaining Input,Action", csv.get_data(as_text=True))

    def test_errors_are_json(self):
        code, d = self.post("/api/parse", grammar="", input="a")
        self.assertEqual((code, d["type"]), (400, "grammar"))
        code, d = self.post("/api/parse", grammar="E E", input="a")
        self.assertEqual(d["errors"][0]["line"], 1)
        code, d = self.post("/api/parse", grammar=ARITH, input="   ")
        self.assertEqual((code, d["type"]), (400, "input"))
        code, d = self.post("/api/parse", grammar=ARITH, input="id+x")
        self.assertEqual((code, d["type"]), (400, "input"))
        code, d = self.post("/api/parse", grammar=ARITH, start="Z", input="id")
        self.assertEqual(code, 400)
        self.assertEqual(self.c.get("/api/nope").status_code, 404)
        self.assertEqual(self.c.get("/api/history/999/csv").status_code, 404)

    def test_analyze(self):
        code, d = self.post("/api/analyze", grammar=ARITH)
        self.assertTrue(d["analysis"]["slr1"])
        self.assertEqual(d["analysis"]["states"], 12)
        self.assertEqual(self.c.get("/api/stats").get_json()["total"], 0)     # analysis is not parsing


if __name__ == "__main__":
    unittest.main(verbosity=2)
