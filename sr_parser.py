"""
sr_parser.py - Shift-reduce parsing engine (SLR(1) driven)
==========================================================
(The file is called sr_parser.py rather than parser.py because Python <= 3.9 ships a
built-in module called "parser" that would shadow it.)

REDUCTION STRATEGY (documented)
-------------------------------
A shift-reduce parser must decide, at every step, whether to SHIFT the next token
or to REDUCE the handle on top of the stack. This engine decides with an SLR(1)
table that it builds from the user's grammar:

  1. Build the canonical collection of LR(0) item sets (the automaton).
  2. ACTION[state, a]:
       * shift  j   if the state has an item  A -> alpha . a beta  and goto(state,a)=j
       * reduce k   if the state has a completed item  A -> gamma .  and  a in FOLLOW(A)
       * accept     if the state has  S' -> S .  and a = $
  3. GOTO[state, A] = state reached after reducing to non-terminal A.

The parser runs the usual loop: look at the state on top of the stack and the
lookahead token, then SHIFT / REDUCE / ACCEPT, or report ERROR if the table has
no entry.

CONFLICTS are never hidden. If a table cell holds more than one action the grammar
is not SLR(1) (typical for ambiguous grammars). The conflict is recorded
(see `conflicts`) and is shown on every step where it matters. It is resolved
deterministically so the parser always terminates:
  * shift/reduce  -> SHIFT (policy "shift", default) or REDUCE (policy "reduce")
  * reduce/reduce -> the production written first in the grammar
Because of this, an ambiguous grammar may reject a string that the grammar does
derive; the report tells the user exactly where this could happen.

INFINITE-LOOP PREVENTION
------------------------
Every configuration (stack of states + input position) is remembered. A repeated
configuration means the parser would cycle forever (e.g. on  A -> B, B -> A), so
parsing stops with an ERROR. A hard step limit (MAX_STEPS) is a second guard.
"""
from grammar import Production, END, EPSILON

MAX_STEPS = 5000


class ShiftReduceParser:
    def __init__(self, grammar, policy="shift"):
        self.g = grammar
        self.policy = policy if policy in ("shift", "reduce") else "shift"
        aug_name = grammar.start + "'"
        while aug_name in grammar.nt_set:
            aug_name += "'"
        # Augmented production  S' -> S  (its index is the last one)
        self.aug = Production(len(grammar.productions), aug_name, (grammar.start,))
        self.prods = grammar.productions + [self.aug]
        self.by_lhs = {}
        for p in grammar.productions:
            self.by_lhs.setdefault(p.lhs, []).append(p.index)
        self._build_automaton()
        self._build_tables()

    # ------------------------------------------------------------ automaton
    def _closure(self, items):
        result, work = set(items), list(items)
        while work:
            pi, dot = work.pop()
            rhs = self.prods[pi].rhs
            if dot < len(rhs) and rhs[dot] in self.g.nt_set:
                for q in self.by_lhs[rhs[dot]]:
                    if (q, 0) not in result:
                        result.add((q, 0))
                        work.append((q, 0))
        return frozenset(result)

    def _goto(self, items, sym):
        moved = {(pi, dot + 1) for pi, dot in items
                 if dot < len(self.prods[pi].rhs) and self.prods[pi].rhs[dot] == sym}
        return self._closure(moved) if moved else None

    def _build_automaton(self):
        start = self._closure({(self.aug.index, 0)})
        self.states, self.trans, index = [start], {}, {start: 0}
        i = 0
        while i < len(self.states):
            items, symbols = self.states[i], []
            for pi, dot in sorted(items):
                rhs = self.prods[pi].rhs
                if dot < len(rhs) and rhs[dot] not in symbols:
                    symbols.append(rhs[dot])
            for sym in symbols:
                nxt = self._goto(items, sym)
                if nxt not in index:
                    index[nxt] = len(self.states)
                    self.states.append(nxt)
                self.trans[(i, sym)] = index[nxt]
            i += 1

    def item_text(self, pi, dot):
        p = self.prods[pi]
        body = list(p.rhs[:dot]) + ["•"] + list(p.rhs[dot:])
        return "%s -> %s" % (p.lhs, " ".join(body))

    # --------------------------------------------------------------- tables
    def _build_tables(self):
        self.action = {}
        for s, items in enumerate(self.states):
            row = {}

            def add(a, entry):
                if entry not in row.setdefault(a, []):
                    row[a].append(entry)

            for pi, dot in items:
                p = self.prods[pi]
                if dot < len(p.rhs):
                    if p.rhs[dot] in self.g.t_set:
                        add(p.rhs[dot], ("s", self.trans[(s, p.rhs[dot])]))
                elif pi == self.aug.index:
                    add(END, ("acc",))
                else:
                    for a in self.g.follow[p.lhs]:
                        add(a, ("r", pi))
            self.action[s] = row
        self.goto = {(s, X): t for (s, X), t in self.trans.items() if X in self.g.nt_set}

        self.conflicts = []
        for s, row in self.action.items():
            for a, entries in row.items():
                if len(entries) > 1:
                    has_shift = any(e[0] == "s" for e in entries)
                    n_red = sum(1 for e in entries if e[0] == "r")
                    kind = ("shift/reduce" if n_red == 1 else "shift/reduce/reduce") if has_shift else "reduce/reduce"
                    self.conflicts.append({
                        "state": s, "symbol": a, "kind": kind,
                        "options": [self._describe(e) for e in entries],
                        "resolution": self._describe(self._choose(entries)),
                    })

    def _describe(self, e):
        if e[0] == "s":
            return "shift to state %d" % e[1]
        if e[0] == "r":
            return "reduce %s" % self.prods[e[1]].text()
        return "accept"

    def _cell(self, e):
        return {"s": "s%d" % e[1] if e[0] == "s" else "", "r": "r%d" % (e[1] + 1) if e[0] == "r" else "",
                "a": "acc"}[e[0][0]]

    def _choose(self, entries):
        """Deterministic conflict resolution (see module docstring)."""
        if len(entries) == 1:
            return entries[0]
        for e in entries:
            if e[0] == "acc":
                return e
        shifts = [e for e in entries if e[0] == "s"]
        reduces = sorted((e for e in entries if e[0] == "r"), key=lambda e: e[1])
        if shifts and reduces:
            return shifts[0] if self.policy == "shift" else reduces[0]
        return (shifts or reduces)[0]

    def table_view(self):
        """ACTION/GOTO tables and LR(0) item sets in a JSON-friendly form."""
        rows = []
        for s, items in enumerate(self.states):
            rows.append({
                "state": s,
                "items": [self.item_text(pi, d) for pi, d in sorted(items)],
                "actions": {a: "/".join(self._cell(e) for e in en) for a, en in self.action[s].items()},
                "gotos": {X: self.trans[(s, X)] for X in self.g.nonterminals if (s, X) in self.trans},
            })
        return {"terminals": self.g.terminals + [END], "nonterminals": self.g.nonterminals, "rows": rows}

    # -------------------------------------------------------------- parsing
    def parse(self, tokens):
        """Run the shift-reduce algorithm and return every step plus the parse tree."""
        inp = list(tokens) + [END]
        stack = [(0, END, None)]              # (state, grammar symbol, parse-tree node)
        pos, steps, seen = 0, [], set()

        def snap(action, detail, explanation, pop=0, prod=None, conflict=None):
            steps.append({
                "step": len(steps) + 1,
                "stack": [x[1] for x in stack], "states": [x[0] for x in stack],
                "input": inp[pos:], "action": action, "detail": detail,
                "explanation": explanation, "pop": pop, "production": prod, "conflict": conflict,
            })

        def finish_error(message):
            snap("ERROR", "ERROR", message)
            return {"accepted": False, "steps": steps, "tree": None, "message": message}

        while True:
            state, la = stack[-1][0], inp[pos]
            config = (tuple(x[0] for x in stack), pos)
            if config in seen:
                return finish_error("Infinite loop detected: the parser returned to an earlier configuration "
                                    "(cyclic reductions such as A -> B and B -> A). Parsing was stopped.")
            if len(steps) >= MAX_STEPS:
                return finish_error("Step limit (%d) reached; parsing was stopped to prevent an endless run." % MAX_STEPS)
            seen.add(config)

            entries = self.action[state].get(la, [])
            if not entries:                                   # ---- ERROR
                expected = self.g.order(self.action[state].keys())
                exp = ", ".join("'%s'" % t for t in expected) or "nothing (dead end)"
                if la == END:
                    msg = "Unexpected end of input in state %d. The parser expected one of: %s." % (state, exp)
                else:
                    msg = "Unexpected token '%s' (token %d of %d) in state %d. The parser expected one of: %s." % (
                        la, pos + 1, len(tokens), state, exp)
                return finish_error(msg)

            choice = self._choose(entries)
            conflict, note = None, ""
            if len(entries) > 1:                              # conflict is exposed, not hidden
                kinds = {e[0] for e in entries}
                kind = "shift/reduce" if "s" in kinds else "reduce/reduce"
                conflict = {"kind": kind, "symbol": la, "state": state,
                            "options": [self._describe(e) for e in entries],
                            "chosen": self._describe(choice), "policy": self.policy}
                note = (" CONFLICT (%s on '%s'): possible actions were [%s]; chose '%s' (%s)."
                        % (kind, la, "; ".join(conflict["options"]), conflict["chosen"],
                           "policy: prefer %s" % self.policy if kind == "shift/reduce" else "earliest production wins"))

            if choice[0] == "acc":                            # ---- ACCEPT
                snap("ACCEPT", "ACCEPT",
                     "The lookahead is $ and the stack holds only the start symbol '%s' on top of $: "
                     "the whole input has been reduced, so the string is accepted." % self.g.start + note,
                     conflict=conflict)
                return {"accepted": True, "steps": steps, "tree": stack[-1][2],
                        "message": "The string is accepted: it can be derived from '%s'." % self.g.start}

            if choice[0] == "s":                              # ---- SHIFT
                snap("SHIFT", "SHIFT",
                     "Lookahead '%s': no complete handle can be reduced, so shift it onto the stack and enter state %d."
                     % (la, choice[1]) + note, conflict=conflict)
                stack.append((choice[1], la, {"symbol": la, "terminal": True, "rule": None, "children": []}))
                pos += 1
                continue

            p = self.prods[choice[1]]                         # ---- REDUCE
            n = len(p.rhs)
            if n:
                why = ("The handle '%s' is on top of the stack and lookahead '%s' is in FOLLOW(%s). "
                       "Pop %d symbol(s) and push %s." % (" ".join(p.rhs), la, p.lhs, n, p.lhs))
            else:
                why = ("ε-production: lookahead '%s' is in FOLLOW(%s), so the empty string is reduced to %s "
                       "(pop 0 symbols, push %s)." % (la, p.lhs, p.lhs, p.lhs))
            snap("REDUCE", "REDUCE " + p.text(), why + note, pop=n, prod=p.index + 1, conflict=conflict)
            children = [x[2] for x in stack[len(stack) - n:]] if n else \
                [{"symbol": EPSILON, "terminal": True, "rule": None, "children": [], "epsilon": True}]
            if n:
                del stack[len(stack) - n:]
            target = self.goto.get((stack[-1][0], p.lhs))
            if target is None:                                # cannot happen for a correct table
                return finish_error("Internal error: no GOTO for %s in state %d." % (p.lhs, stack[-1][0]))
            stack.append((target, p.lhs, {"symbol": p.lhs, "terminal": False, "rule": p.text(), "children": children}))
