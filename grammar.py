"""
grammar.py - Grammar model for ShiftReduce Studio
=================================================
Responsibilities
  * turn the grammar text typed by the user into Production objects
  * validate it and report meaningful, line-numbered errors
  * compute grammar analysis: nullable non-terminals, FIRST and FOLLOW sets
  * tokenise the input string typed by the user

Grammar syntax
  * One rule per line:      A -> alpha | beta      (also accepted: ->, → and ::=)
  * A line that starts with '|' continues the previous rule.
  * Epsilon (empty) production: ε  (or: epsilon, eps, λ, lambda)
  * Lines starting with '#' are comments.
  * Every symbol that appears on a left-hand side is a NON-TERMINAL; every other
    symbol is a TERMINAL.
  * Symbol splitting:
      - If at least one alternative contains whitespace-separated symbols
        (e.g. "E + T") the grammar is in "spaced" mode: a word is one symbol,
        e.g. the word  id  is ONE terminal.
      - Otherwise ("compact" mode, e.g. "aSb") every character is one symbol.
      - Words that mix non-terminal names with other characters (e.g. "aSb",
        "(E)") are always split around the non-terminal names.
      - A quoted word such as 'id' is always exactly one terminal.
"""
import re

EPSILON = "ε"
END = "$"
EPS_WORDS = {"ε", "epsilon", "eps", "λ", "lambda"}
ARROW = re.compile(r"\s*(?:->|→|::=)\s*")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*$")
WORD = re.compile(r"'[^'\s]+'|\"[^\"\s]+\"|\S+")
MAX_GRAMMAR_CHARS = 20000


class GrammarError(Exception):
    """Raised when the grammar text is invalid. `errors` is a list of dicts."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(e["message"] for e in errors))


class InputError(Exception):
    """Raised when the input string contains symbols that are not terminals."""

    def __init__(self, message, unknown=None):
        self.unknown = unknown or []
        super().__init__(message)


def _err(line, text, message):
    return {"line": line, "text": text, "message": message}


class Production:
    __slots__ = ("index", "lhs", "rhs")

    def __init__(self, index, lhs, rhs):
        self.index = index          # 0-based; displayed to the user as index + 1
        self.lhs = lhs
        self.rhs = tuple(rhs)

    def text(self):
        return "%s -> %s" % (self.lhs, " ".join(self.rhs) if self.rhs else EPSILON)


def _split_alt(alt, nts, spaced):
    """Split one alternative (text) into a list of grammar symbols."""
    if alt.lower() in EPS_WORDS:
        return []
    names = sorted(nts, key=len, reverse=True)       # longest non-terminal name wins
    symbols = []
    for w in WORD.findall(alt):
        if len(w) > 2 and w[0] in "'\"" and w[-1] == w[0]:
            symbols.append(w[1:-1])                  # quoted terminal
            continue
        if w in nts:
            symbols.append(w)
            continue
        buf, i = "", 0
        while i < len(w):
            m = next((n for n in names if w.startswith(n, i)), None)
            if m:
                if buf:
                    symbols.extend([buf] if spaced else list(buf))
                    buf = ""
                symbols.append(m)
                i += len(m)
            else:
                buf += w[i]
                i += 1
        if buf:
            symbols.extend([buf] if spaced else list(buf))
    return symbols


class Grammar:
    def __init__(self, productions, start, nonterminals, terminals, spaced, warnings):
        self.productions = productions
        self.start = start
        self.nonterminals = nonterminals
        self.terminals = terminals
        self.spaced = spaced
        self.warnings = warnings
        self.nt_set = set(nonterminals)
        self.t_set = set(terminals)
        self.nullable, self.first, self.follow = set(), {}, {}
        self._compute_sets()
        self._check_symbols()

    # ------------------------------------------------------------------ parsing
    @classmethod
    def from_text(cls, text, start=None):
        if len(text) > MAX_GRAMMAR_CHARS:
            raise GrammarError([_err(None, "", "Grammar is too long (limit %d characters)." % MAX_GRAMMAR_CHARS)])
        errors, rules, last_lhs = [], [], None
        for no, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("|"):                                   # continuation line
                if last_lhs is None:
                    errors.append(_err(no, s, "An alternative '|' appears before any rule. Start with  A -> ..."))
                    continue
                lhs, body = last_lhs, s[1:]
            else:
                parts = ARROW.split(s, 1)
                if len(parts) != 2:
                    errors.append(_err(no, s, "Missing arrow. Write rules as  A -> alpha | beta  (→ and ::= also work)."))
                    continue
                lhs, body = parts[0].strip(), parts[1]
                if not lhs:
                    errors.append(_err(no, s, "The left-hand side is empty."))
                    continue
                if not NAME.match(lhs) or lhs.lower() in EPS_WORDS:
                    errors.append(_err(no, s, "'%s' is not a valid non-terminal name. Use letters, digits, _ or ' and start with a letter." % lhs))
                    continue
                if ARROW.search(body):
                    errors.append(_err(no, s, "More than one arrow on a single line. Put each rule on its own line."))
                    continue
                last_lhs = lhs
            alts = [a.strip() for a in body.split("|")]
            if any(a == "" for a in alts):
                errors.append(_err(no, s, "Empty alternative. Write ε (or 'epsilon') for an empty production."))
                continue
            rules.append((no, s, lhs, alts))
        if not rules and not errors:
            errors.append(_err(None, "", "The grammar is empty. Enter at least one production."))
        if errors:
            raise GrammarError(errors)

        nts = []
        for _, _, lhs, _ in rules:
            if lhs not in nts:
                nts.append(lhs)
        start = (start or "").strip() or nts[0]
        if start not in nts:
            raise GrammarError([_err(None, start, "Start symbol '%s' is not defined: it has no production. Defined non-terminals: %s." % (start, ", ".join(nts)))])

        nt_set = set(nts)
        spaced = any(len(WORD.findall(a)) > 1 for _, _, _, alts in rules for a in alts if a.lower() not in EPS_WORDS)
        prods, seen, warnings, terminals = [], set(), [], []
        for no, s, lhs, alts in rules:
            for a in alts:
                rhs = tuple(_split_alt(a, nt_set, spaced))
                if END in rhs:
                    errors.append(_err(no, s, "'$' is reserved as the end-of-input marker and cannot be used in a grammar."))
                if EPSILON in rhs and len(rhs) > 1:
                    errors.append(_err(no, s, "ε must be the only symbol of an alternative."))
                if (lhs, rhs) in seen:
                    warnings.append("Line %d: duplicate production '%s' was ignored." % (no, Production(0, lhs, rhs).text()))
                    continue
                seen.add((lhs, rhs))
                prods.append(Production(len(prods), lhs, rhs))
                for sym in rhs:
                    if sym not in nt_set and sym not in terminals:
                        terminals.append(sym)
        if errors:
            raise GrammarError(errors)
        return cls(prods, start, nts, terminals, spaced, warnings)

    # ----------------------------------------------------------------- analysis
    def first_of(self, seq):
        """FIRST of a symbol sequence -> (set of terminals, sequence_is_nullable)."""
        result = set()
        for s in seq:
            if s in self.nt_set:
                result |= self.first[s]
                if s not in self.nullable:
                    return result, False
            else:
                result.add(s)
                return result, False
        return result, True

    def _compute_sets(self):
        # Nullable: A is nullable if some production A -> X1..Xn has all Xi nullable.
        changed = True
        while changed:
            changed = False
            for p in self.productions:
                if p.lhs not in self.nullable and all(s in self.nullable for s in p.rhs):
                    self.nullable.add(p.lhs)
                    changed = True
        # FIRST: fixed-point iteration.
        self.first = {n: set() for n in self.nonterminals}
        changed = True
        while changed:
            changed = False
            for p in self.productions:
                f, _ = self.first_of(p.rhs)
                if not f <= self.first[p.lhs]:
                    self.first[p.lhs] |= f
                    changed = True
        # FOLLOW: $ follows the start symbol; propagate through productions.
        self.follow = {n: set() for n in self.nonterminals}
        self.follow[self.start].add(END)
        changed = True
        while changed:
            changed = False
            for p in self.productions:
                for i, s in enumerate(p.rhs):
                    if s not in self.nt_set:
                        continue
                    f, nullable_rest = self.first_of(p.rhs[i + 1:])
                    new = set(f)
                    if nullable_rest:
                        new |= self.follow[p.lhs]
                    if not new <= self.follow[s]:
                        self.follow[s] |= new
                        changed = True

    def _check_symbols(self):
        for t in self.terminals:
            if t[0].isupper() and NAME.match(t):
                self.warnings.append("'%s' looks like a non-terminal but has no production, so it is treated as a terminal (missing production?)." % t)
        reach, work = {self.start}, [self.start]
        while work:
            n = work.pop()
            for p in self.productions:
                if p.lhs == n:
                    for s in p.rhs:
                        if s in self.nt_set and s not in reach:
                            reach.add(s)
                            work.append(s)
        unreachable = [n for n in self.nonterminals if n not in reach]
        if unreachable:
            self.warnings.append("Unreachable non-terminal(s) (never derived from the start symbol): %s." % ", ".join(unreachable))
        productive, changed = set(), True
        while changed:
            changed = False
            for p in self.productions:
                if p.lhs not in productive and all(s in self.t_set or s in productive for s in p.rhs):
                    productive.add(p.lhs)
                    changed = True
        unproductive = [n for n in self.nonterminals if n not in productive]
        if unproductive:
            self.warnings.append("Non-terminal(s) that cannot derive any terminal string: %s." % ", ".join(unproductive))

    def order(self, symbols):
        """Sort terminals in order of first appearance ($ last)."""
        pos = {t: i for i, t in enumerate(self.terminals)}
        return sorted(symbols, key=lambda t: (t == END, pos.get(t, 0)))

    def to_dict(self):
        return {
            "start": self.start,
            "mode": "spaced" if self.spaced else "compact",
            "nonterminals": self.nonterminals,
            "terminals": self.terminals,
            "productions": [{"index": p.index + 1, "lhs": p.lhs, "rhs": list(p.rhs), "text": p.text()}
                            for p in self.productions],
            "nullable": [n for n in self.nonterminals if n in self.nullable],
            "first": {n: self.order(self.first[n]) + ([EPSILON] if n in self.nullable else [])
                      for n in self.nonterminals},
            "follow": {n: self.order(self.follow[n]) for n in self.nonterminals},
            "warnings": self.warnings,
        }


def tokenize(text, terminals):
    """Split the input string into terminals using greedy longest-match."""
    s = text.strip()
    if s.lower() in EPS_WORDS:                      # the empty string
        return []
    terms = sorted(terminals, key=len, reverse=True)
    tokens, bad, i = [], [], 0
    while i < len(s):
        if s[i].isspace():
            i += 1
            continue
        m = next((t for t in terms if s.startswith(t, i)), None)
        if m:
            tokens.append(m)
            i += len(m)
            continue
        j = i + 1
        while j < len(s) and not s[j].isspace() and not any(s.startswith(t, j) for t in terms):
            j += 1
        bad.append({"position": i + 1, "text": s[i:j]})
        i = j
    if bad:
        shown = ", ".join("'%s' at position %d" % (b["text"], b["position"]) for b in bad[:5])
        raise InputError("Unknown terminal(s): %s. The terminals of this grammar are: %s."
                         % (shown, ", ".join(terminals) or "(none)"), bad)
    return tokens
