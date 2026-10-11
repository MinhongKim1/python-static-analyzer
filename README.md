# Python Static Analyzer

This project is a control-flow-graph (CFG)–based static analyzer for a subset of Python. It examines source code without executing it and reports potential variable-definition problems, unreachable code, dead stores, and unused local variables. Important concepts incorporated in this project include AST traversal, basic blocks, control-flow modeling, forward and backward data-flow analysis, and fixed-point iteration.


## Features

- **Control-Flow Graph (CFG):** Builds a graph of the different execution paths a Python program can take, including branches, loops, break, continue, return, and raise.
- **Forward Data-Flow Analysis:** Tracks which variables are defined and their known values to detect undefined variables and unreachable code.
- **Backward Data-Flow Analysis:** Tracks whether variables are used later to detect unused variables and dead stores.
- **Worklist Algorithm:** Repeatedly analyzes blocks until the variable information stops changing.
- **Counterexample Paths:** Shows a possible execution path that could lead to an undefined variable.

## Quick Start

Clone the Git repo and install the package:

```bash
git clone https://github.com/MinhongKim1/python-static-analyzer.git
cd python-static-analyzer
pip install -e .
```

Run the analyzer on a Python file:

```bash
pyanalyze demo.py
```

To display the control-flow graph:

```bash
pyanalyze demo.py --cfg
```

## How It Works

```text
Python source
    |
    v
Python AST (ast.parse)
    |
    v
CFG construction (basic blocks + control-flow edges)
    |
    v
Forward analysis (variable definitions + constant propagation)
    |
    +--> Determine reachable blocks and possible execution paths
    |
    v
Backward analysis (live-variable analysis)
    |
    v
Diagnostics (warnings + counterexample paths)
```

1. **Parse:** Use Python's `ast` module to convert source code into an abstract syntax tree.
2. **Build the CFG:** Split the code into basic blocks and connect them based on possible execution paths.
3. **Forward analysis:** Track defined variables and known constant values across the CFG until the information stops changing.
4. **Backward analysis:** Work backward through the CFG to determine which variables might be used later.
5. **Diagnostics:** Report undefined variables, unreachable code, dead stores, and unused variables. It also reports  possible execution paths for undefined-variable warnings.

## Project Structure

```text
python-static-analyzer/
├── pyanalyzer/
│   ├── analysis.py       # Forward data-flow analysis and constant propagation
│   ├── cfg.py            # Control-flow graph construction
│   ├── liveness.py       # Backward live-variable analysis
│   ├── diagnostics.py    # Detects issues and generates warnings
│   └── cli.py            # Command-line interface
├── tests/
│   └── test_analyzer.py  # Unit and integration tests
├── demo.py               # Example Python program
├── pyproject.toml        # Project configuration
└── README.md             # Project documentation
```

## Scope

This project supports common Python constructs such as conditionals, loops, and variable assignments. Other advanced features including exception handling (`try/except/finally`), nested functions, and dynamic Python features such as reflection, are outside the current project scope.

