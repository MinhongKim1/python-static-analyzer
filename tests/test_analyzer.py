import ast

from pyanalyzer.analysis import analyze_cfg
from pyanalyzer.cfg import CFGBuilder
from pyanalyzer.diagnostics import diagnose


def analyze(source):
    tree = ast.parse(source)
    function = tree.body[0]

    cfg = CFGBuilder().build(function)

    params = tuple(
        arg.arg
        for arg in function.args.args
    )

    result = analyze_cfg(
        cfg,
        params,
    )

    return diagnose(
        cfg,
        result,
        params,
    )


def rules(source):
    return [
        diagnostic.rule
        for diagnostic in analyze(source)
    ]


def test_defined_variable():
    assert analyze("""
def foo():
    x = 5
    return x
""") == []


def test_undefined_variable():
    diagnostics = analyze("""
def foo():
    return x
""")

    assert len(diagnostics) == 1

    assert (
        diagnostics[0].rule
        == "POSSIBLY_UNDEFINED"
    )


def test_branch_maybe_undefined():
    diagnostics = analyze("""
def foo(x):
    if x > 0:
        y = 5

    return y
""")

    assert (
        "POSSIBLY_UNDEFINED"
        in [
            diagnostic.rule
            for diagnostic in diagnostics
        ]
    )


def test_counterexample_path():
    diagnostics = analyze("""
def foo(x):
    if x > 0:
        y = 5

    return y
""")

    diagnostic = next(
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.rule == "POSSIBLY_UNDEFINED"
    )

    assert diagnostic.path
    assert any(
        "false" in step
        for step in diagnostic.path
    )
    assert any(
        "return y" in step
        for step in diagnostic.path
    )


def test_defined_both_paths():
    assert analyze("""
def foo(x):
    if x > 0:
        y = 5
    else:
        y = 10

    return y
""") == []


def test_constant_branch_pruning():
    diagnostics = analyze("""
def foo():
    x = 5

    if x > 10:
        y = 1
    else:
        y = 2

    return y
""")

    assert "UNREACHABLE" in [
        diagnostic.rule
        for diagnostic in diagnostics
    ]

    assert (
        "POSSIBLY_UNDEFINED"
        not in [
            diagnostic.rule
            for diagnostic in diagnostics
        ]
    )


def test_constant_propagation():
    diagnostics = analyze("""
def foo():
    x = 5
    y = x + 5

    if y == 10:
        result = 1
    else:
        result = 2

    return result
""")

    assert "UNREACHABLE" in [
        diagnostic.rule
        for diagnostic in diagnostics
    ]


def test_after_return_unreachable():
    diagnostics = analyze("""
def foo():
    return 1
    x = 5
""")

    assert "UNREACHABLE" in [
        diagnostic.rule
        for diagnostic in diagnostics
    ]


def test_loop():
    diagnostics = analyze("""
def foo(x):
    while x > 0:
        x = x - 1

    return x
""")

    assert diagnostics == []