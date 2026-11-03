# ShiftReduce Studio
### Design and Implementation of a Shift-Reduce Parsing Simulator for Context-Free Grammars

An interactive Flask web application that validates context-free grammars, analyses them (nullable symbols, FIRST, FOLLOW), builds an SLR(1) parser automaton and runs a **real** shift-reduce parser, step by step, with a live stack/input visualisation and an SVG parse tree. No result is hard-coded: every step comes from the grammar you type.

## Project structure
```
ShiftReduceStudio/
├── app.py              Flask routes, JSON API, history, statistics, CSV export
├── grammar.py          Grammar parsing/validation, nullable, FIRST, FOLLOW, input tokeniser
├── sr_parser.py        LR(0) automaton, SLR(1) table, conflict handling, shift-reduce engine, parse tree
├── tests.py            Automated tests (python tests.py)
├── requirements.txt
├── templates/          base, index (dashboard), simulator, algorithm, history, about
├── static/css/style.css
├── static/js/script.js
├── static/images/logo.svg
└── README.md
```
`sr_parser.py` is deliberately not called `parser.py`: Python 3.9 and older ship a built-in module named `parser` that would shadow it.

## Installation and running (Windows, PowerShell or cmd)
```bat
cd ShiftReduceStudio
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open **http://127.0.0.1:5000** (the browser also opens automatically). Stop with `Ctrl+C`. In PowerShell, if activation is blocked run `Set-ExecutionPolicy -Scope Process RemoteSigned` first. macOS/Linux: `source venv/bin/activate`.

### Troubleshooting
| Problem | Fix |
|---|---|
| `'python' is not recognized` | Install Python 3.8+ from python.org and tick *Add Python to PATH*; or use `py -m venv venv` / `py app.py`. |
| `No module named flask` | Activate the virtual environment, then `pip install -r requirements.txt`. |
| `Address already in use` (port 5000) | Close the other program, or change `port` at the bottom of `app.py`. |
| Page shows "Cannot reach the server" | The terminal running `python app.py` was closed; start it again. |
| `ε`, `•` look wrong in Excel | The CSV has a UTF-8 BOM; use *Data > From Text/CSV* with UTF-8 if needed. |

## Testing
```bat
python tests.py
```
Covers: `id+id`, `id*id`, `id+id*id`, `(id+id)*id` (accepted) and `id+`, `+id`, `id*id+` (rejected); the exact step trace of `id+id`; tree shape and precedence; ε-productions (including the empty string); FIRST/FOLLOW; shift/reduce conflicts with both policies; infinite-loop protection; invalid grammars; unknown terminals; every page and API route.

**Manual check:** open *Simulator*, load *Arithmetic expressions*, parse `id+id*id`, press *Next* repeatedly and watch the stack, remaining input, badge colour and explanation change; open the *Parse tree* tab.

## Grammar syntax
```
E -> E + T | T          # one rule per line, | separates alternatives
T -> T * F | F
F -> ( E ) | id
A -> a A | ε            # ε, epsilon, eps, λ or lambda = empty production
  | b                   # a line starting with | continues the previous rule
```
* Symbols on a left-hand side are non-terminals; every other symbol is a terminal.
* If any alternative has space-separated symbols (`E + T`) a word is one symbol (`id` is one terminal). Otherwise (`S -> aSb | ab`) each character is one symbol. Words mixing non-terminals with other characters (`aSb`, `(E)`) are split around the non-terminals. Quote a word (`'id'`) to force a single terminal.
* `$` is reserved as the end marker. Type `ε` as the input to parse the empty string.

---

# College project documentation

## 1. Abstract
Syntax analysis is a core phase of a compiler, and bottom-up shift-reduce parsing is the basis of most practical parser generators. This project presents ShiftReduce Studio, a web-based simulator that accepts an arbitrary context-free grammar, constructs the LR(0) automaton and SLR(1) parsing table, and executes the shift-reduce algorithm on user-supplied strings. Each SHIFT, REDUCE, ACCEPT and ERROR action is recorded and visualised, a parse tree is generated for accepted strings, and grammar properties such as nullable symbols, FIRST and FOLLOW sets and parsing conflicts are reported.

## 2. Introduction
A parser checks whether a token sequence conforms to the grammar of a language and recovers its structure. Top-down parsers expand the start symbol; bottom-up parsers start from the tokens and reduce them back to the start symbol, tracing a right-most derivation in reverse. Shift-reduce parsing implements this with a stack and an input buffer.

## 3. Problem Statement
Shift-reduce parsing is difficult to learn from static textbook tables: students cannot easily see how the stack, input and automaton interact, why a conflict arises, or how the tree emerges. A tool is needed that runs the genuine algorithm on any grammar and makes every step observable.

## 4. Objectives
* Implement a working shift-reduce parser driven by the user's grammar, with no faked results.
* Visualise the stack, remaining input and action at every step, with navigation and auto-play.
* Generate parse trees for accepted strings.
* Report grammar analysis (nullable, FIRST, FOLLOW) and expose parsing conflicts rather than hide them.
* Give clear errors for invalid grammars and inputs, and prevent infinite loops.

## 5. Scope of Project
Context-free grammars in BNF-like notation, including ε-productions and ambiguous grammars; SLR(1)-driven shift-reduce parsing of strings up to 500 tokens; a local, single-user web interface. Lexical analysis (scanning real source code) and semantic analysis are outside the scope.

## 6. Existing System
Command-line programs and generators (Yacc/Bison, textbook worked examples) produce tables or code but hide the parsing steps; most classroom demonstrations are slides with hand-made traces. Existing visualisers are often fixed to a single grammar or require installation of heavy tooling.

## 7. Proposed System
A self-contained web application: the Python back end builds the automaton and executes the algorithm; the JavaScript front end renders the step table, stack chips, explanations and SVG tree. It runs offline with only Flask installed.

## 8. System Architecture
```
Browser (HTML/CSS/JS)  ── JSON over HTTP ──►  Flask (app.py)
  grammar editor, step controller,               │ routes, validation, history, stats
  trace table, SVG tree, tables                  ├─► grammar.py     parse + validate grammar, FIRST/FOLLOW, tokeniser
                                                 └─► sr_parser.py   LR(0) items → SLR(1) table → shift-reduce loop → tree
```
API: `GET /api/samples`, `GET /api/stats`, `POST /api/analyze`, `POST /api/parse`, `GET /api/history`, `GET /api/history/<id>/csv`, `POST /api/reset`.

## 9. Modules
1. **Dashboard** – project summary, live statistics (grammars tested, accepted, rejected), quick start, example.
2. **Grammar input** – editor, start symbol, live validation with line-numbered errors, formatted production table, samples.
3. **Input string** – entry, default example, clear, conflict policy, accepted/rejected banner.
4. **Parsing engine** (`sr_parser.py`) – automaton, table, SHIFT/REDUCE/ACCEPT/ERROR loop, conflict reporting, loop guard.
5. **Live visualisation** – Next, Previous, Auto-play with speed, Reset, clickable trace, stack and input chips, explanations.
6. **Parse tree** – SVG tree with production labels.
7. **Grammar analysis** – non-terminals, terminals, nullable, FIRST/FOLLOW, warnings, conflicts, ACTION/GOTO table, item sets (kept separate from parsing).
8. **History and export** – past runs, re-open a run, CSV download, reset.
9. **Algorithm and About pages**.

## 10. Shift-Reduce Parsing Algorithm
1. Augment the grammar with `S' -> S`.
2. Build LR(0) item sets with *closure* and *goto*; each set is a parser state.
3. Compute nullable, FIRST and FOLLOW.
4. Fill ACTION: shift on terminals after the dot; reduce `A -> γ` on every terminal in FOLLOW(A); accept on `$` for `S' -> S •`. Fill GOTO for non-terminals.
5. Execute: put state 0 on the stack; repeat – read the state on top and the lookahead, then

| Table entry | Action | Effect |
|---|---|---|
| `shift j` | **SHIFT** | push the token and state j, advance input |
| `reduce A -> β` | **REDUCE** | pop \|β\| entries (none for ε), push A and GOTO state, build a tree node |
| `accept` | **ACCEPT** | stop; the string is in the language, the tree root is the start symbol |
| empty | **ERROR** | stop; report the unexpected token and the expected ones |

**Conflicts.** A cell with several actions means the grammar is not SLR(1) (typically ambiguity). Conflicts are listed in the analysis tab and flagged on each affected step. Resolution: shift/reduce uses the chosen policy (SHIFT by default), reduce/reduce takes the production written first.

**Loop prevention.** Configurations (state stack + input position) are remembered; a repeat means a reduction cycle and stops with ERROR. A 5000-step limit is a second guard.

**How the four actions appear in the application:** SHIFT rows are blue, REDUCE rows purple (the handle is highlighted on the stack), ACCEPT is green and ends the trace with the parse tree, ERROR is red and states the unexpected token and the tokens that were expected.

## 11. Hardware and Software Requirements
*Hardware:* any PC with 2 GB RAM, 200 MB free disk. *Software:* Windows 10/11 (also macOS/Linux), Python 3.8 or later, Flask 2.3+, a modern browser (Chrome, Edge, Firefox). No internet connection or paid service is needed.

## 12. Advantages
* Real algorithm on any grammar; nothing hard-coded.
* Every step visible, explained and exportable.
* Conflicts and ambiguity are exposed, not hidden.
* Offline, lightweight, single command to run.
* Automated test suite.

## 13. Limitations
* SLR(1) only: some unambiguous LR(1)/LALR(1) grammars show conflicts here, and an ambiguous grammar may reject a string the grammar derives if the conflict resolution picks the other branch.
* Symbol splitting relies on whitespace/quoting rules (see Grammar syntax).
* History and statistics are in memory and reset on server restart.
* One parse tree (the one selected by the resolution policy) is shown; all derivations of an ambiguous string are not enumerated.

## 14. Future Enhancements
LR(1) and LALR(1) table construction; GLR parsing to enumerate all parses of ambiguous grammars; operator-precedence declarations to resolve conflicts like Yacc; error recovery; a lexer for real source code; export of the tree as an image; persistent storage and user accounts.

## 15. Conclusion
ShiftReduce Studio demonstrates bottom-up parsing end to end: grammar analysis, automaton and table construction, and a genuine shift-reduce parser whose SHIFT, REDUCE, ACCEPT and ERROR actions are visualised live. It turns an abstract compiler-construction topic into something that can be explored interactively and verified automatically.
