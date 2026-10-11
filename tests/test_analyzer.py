"""Integration and regression tests for the supported Python subset.

Run from the repository root with: python -m pytest -q
"""

import ast

import pytest

from pyanalyzer.analysis import State, analyze_cfg, eval_expr, merge, transfer
from pyanalyzer.cfg import CFGBuilder
from pyanalyzer.diagnostics import diagnose, read_names
from pyanalyzer.liveness import analyze_liveness


# ---- Shared test helpers ---------------------------------------------------

def report(source):
    """Return (CFG, forward-analysis result, diagnostics) for one function."""
    tree = ast.parse(source)
    assert len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef)
    function = tree.body[0]
    parameters = tuple(
        arg.arg
        for arg in (
            function.args.posonlyargs
            + function.args.args
            + function.args.kwonlyargs
        )
    )
    cfg = CFGBuilder().build(function)
    forward = analyze_cfg(cfg, parameters)
    diagnostics = diagnose(cfg, forward, parameters)
    return cfg, forward, diagnostics


def issues(source):
    return report(source)[2]


def matching(source, rule):
    return [d for d in issues(source) if d.rule == rule]


def rule_lines(source, rule):
    return [d.line for d in matching(source, rule)]


# ---- CFG construction and supported control flow ---------------------------

class TestCFG:
    @pytest.mark.parametrize("source", [
        "def f():\n    x = 1\n    return x\n",
        "def f(flag):\n    if flag:\n        return 1\n    return 2\n",
        "def f(x):\n    while x > 0:\n        x -= 1\n    return x\n",
        "def f(xs):\n    for x in xs:\n        print(x)\n",
        "def f(xs):\n    for x in xs:\n        break\n    else:\n        print('done')\n",
        "def f(flag):\n    while flag:\n        break\n    else:\n        print('done')\n",
    ])
    def test_all_edges_point_to_existing_blocks(self, source):
        cfg, _, _ = report(source)
        assert cfg.entry in cfg.blocks
        for block in cfg.blocks.values():
            for edge in block.edges:
                assert edge.target in cfg.blocks

    def test_if_has_true_and_false_branches(self):
        cfg, _, _ = report("def f(flag):\n    if flag:\n        x = 1\n    else:\n        x = 2\n    return x\n")
        assert any({edge.truth for edge in block.edges} == {True, False}
                   for block in cfg.blocks.values())

    @pytest.mark.parametrize("body", [
        "try:\n    x = 1\nexcept Exception:\n    pass",
        "x, y = 1, 2",
        "def nested():\n    pass",
        "x = (y := 3)",
        "with open('file') as f:\n    pass",
    ])
    def test_unsupported_constructs_are_rejected(self, body):
        source = "def f():\n" + "\n".join("    " + line for line in body.splitlines()) + "\n"
        with pytest.raises(SyntaxError):
            report(source)

    def test_bare_raise_is_rejected(self):
        with pytest.raises(SyntaxError, match="bare raise"):
            report("def f():\n    raise\n")

    def test_tuple_for_target_is_rejected(self):
        with pytest.raises(SyntaxError, match="simple for-loop targets"):
            report("def f(xs):\n    for a, b in xs:\n        pass\n")


# ---- Forward analysis: definitions and constant propagation ----------------

class TestForwardAnalysis:
    def test_defined_variable(self):
        assert issues("def f():\n    x = 5\n    return x\n") == []

    def test_undefined_variable(self):
        assert rule_lines("def f():\n    return x\n", "POSSIBLY_UNDEFINED") == [2]

    def test_branch_may_leave_variable_undefined(self):
        assert rule_lines("def f(flag):\n    if flag:\n        y = 5\n    return y\n", "POSSIBLY_UNDEFINED") == [4]

    def test_defined_on_both_branches(self):
        assert not matching("def f(flag):\n    if flag:\n        y = 5\n    else:\n        y = 10\n    return y\n", "POSSIBLY_UNDEFINED")

    def test_counterexample_path_shows_false_branch(self):
        warning = matching("def f(flag):\n    if flag:\n        y = 5\n    return y\n", "POSSIBLY_UNDEFINED")[0]
        assert warning.path
        assert any("false" in step for step in warning.path)
        assert any("return y" in step for step in warning.path)

    def test_constant_condition_prunes_branch(self):
        source = "def f():\n    x = 5\n    if x > 10:\n        y = 1\n    else:\n        y = 2\n    return y\n"
        assert matching(source, "UNREACHABLE")
        assert not matching(source, "POSSIBLY_UNDEFINED")

    def test_constant_propagation(self):
        source = "def f():\n    x = 5\n    y = x + 5\n    if y == 10:\n        result = 1\n    else:\n        result = 2\n    return result\n"
        assert matching(source, "UNREACHABLE")

    def test_augassign_updates_constant(self):
        source = "def f():\n    x = 5\n    x += 1\n    if x == 5:\n        return 1\n    return 2\n"
        assert rule_lines(source, "UNREACHABLE")

    def test_augassign_reads_undefined_lhs(self):
        assert rule_lines("def f():\n    x += 1\n", "POSSIBLY_UNDEFINED") == [2]

    def test_annotated_initialized(self):
        assert issues("def f():\n    x: int = 5\n    return x\n") == []

    def test_annotation_without_value_is_not_assignment(self):
        assert rule_lines("def f():\n    x: int\n    return x\n", "POSSIBLY_UNDEFINED") == [3]

    def test_deletion_removes_definition(self):
        assert rule_lines("def f():\n    x = 5\n    del x\n    return x\n", "POSSIBLY_UNDEFINED") == [4]

    def test_chained_assignment(self):
        assert issues("def f():\n    x = y = 5\n    return x + y\n") == []

    def test_read_names_augassign(self):
        assert read_names(ast.parse("x += y").body[0]) == {"x", "y"}

    def test_builtin_print_is_not_undefined(self):
        assert not matching("def f():\n    print(5)\n", "POSSIBLY_UNDEFINED")

    def test_loop_preserves_parameter_definition(self):
        assert issues("def f(x):\n    while x > 0:\n        x -= 1\n    return x\n") == []

    def test_for_body_target_defined(self):
        assert not matching("def f(xs):\n    for item in xs:\n        print(item)\n", "POSSIBLY_UNDEFINED")

    def test_for_target_not_defined_after_zero_iterations(self):
        source = "def f(xs):\n    for item in xs:\n        pass\n    print(item)\n"
        assert any("'item'" in d.message for d in matching(source, "POSSIBLY_UNDEFINED"))

    def test_for_break_skips_else(self):
        source = "def f(xs):\n    for item in xs:\n        break\n    else:\n        only_else = 5\n    print(only_else)\n"
        assert any("'only_else'" in d.message for d in matching(source, "POSSIBLY_UNDEFINED"))

    def test_for_else_runs_after_normal_completion(self):
        source = "def f(xs):\n    for item in xs:\n        pass\n    else:\n        x = 5\n    print(x)\n"
        assert not matching(source, "POSSIBLY_UNDEFINED")

    def test_while_false_skips_body_but_runs_else(self):
        source = "def f():\n    while False:\n        print(missing)\n    else:\n        x = 5\n    print(x)\n"
        assert matching(source, "UNREACHABLE")
        assert not matching(source, "POSSIBLY_UNDEFINED")

    def test_while_break_can_skip_else(self):
        source = "def f(flag):\n    while flag:\n        break\n    else:\n        x = 5\n    print(x)\n"
        assert any("'x'" in d.message for d in matching(source, "POSSIBLY_UNDEFINED"))

    def test_nested_break_only_exits_inner_loop(self):
        source = "def f(xs, ys):\n    for x in xs:\n        for y in ys:\n            break\n        print(x)\n"
        assert not matching(source, "POSSIBLY_UNDEFINED")

    def test_merge_intersects_definitions(self):
        merged = merge([
            State(frozenset({"a", "b"}), {"a": 1, "b": 2}),
            State(frozenset({"a", "c"}), {"a": 1, "c": 3}),
        ])
        assert merged.defined == frozenset({"a"})
        assert merged.constants == {"a": 1}

    def test_merge_discards_disagreeing_constants(self):
        merged = merge([
            State(frozenset({"x"}), {"x": 1}),
            State(frozenset({"x"}), {"x": 2}),
        ])
        assert merged.defined == frozenset({"x"})
        assert "x" not in merged.constants

    def test_transfer_deletes_name(self):
        initial = State(frozenset({"x"}), {"x": 5})
        updated = transfer(ast.parse("del x").body[0], initial)
        assert "x" not in updated.defined
        assert "x" not in updated.constants


# ---- Diagnostics: unreachable code, liveness, dead stores, unused locals ---

class TestDiagnostics:
    def test_code_after_return_is_unreachable(self):
        assert rule_lines("def f():\n    return 1\n    x = 5\n", "UNREACHABLE") == [3]

    def test_code_after_raise_is_unreachable(self):
        assert rule_lines("def f():\n    raise ValueError('bad')\n    print('never')\n", "UNREACHABLE") == [3]

    def test_overwritten_assignment_is_dead(self):
        source = "def f():\n    x = 10\n    x = 20\n    return x\n"
        assert rule_lines(source, "DEAD_STORE") == [2]
        assert not matching(source, "UNUSED_VARIABLE")

    def test_unused_variable_reported_once(self):
        source = "def f():\n    y = 30\n    y = 40\n    return 1\n"
        assert rule_lines(source, "UNUSED_VARIABLE") == [2]
        assert not matching(source, "DEAD_STORE")

    def test_unused_parameter_is_not_unused_local(self):
        assert not matching("def f(param):\n    return 42\n", "UNUSED_VARIABLE")

    def test_branch_read_keeps_previous_store_live(self):
        source = "def f(flag):\n    x = 3\n    if flag:\n        print(x)\n    return 0\n"
        assert not matching(source, "DEAD_STORE")
        assert not matching(source, "UNUSED_VARIABLE")

    def test_augassign_reads_previous_value(self):
        assert not matching("def f():\n    x = 1\n    x += 2\n    return x\n", "DEAD_STORE")

    def test_rhs_read_keeps_previous_store_live(self):
        assert not matching("def f():\n    x = 1\n    y = x + 2\n    return y\n", "DEAD_STORE")

    def test_while_body_read_keeps_store_live(self):
        source = "def f(flag):\n    x = 1\n    while flag:\n        print(x)\n        break\n    return 0\n"
        assert not matching(source, "DEAD_STORE")

    def test_used_for_target_is_not_unused(self):
        source = "def f(xs):\n    for x in xs:\n        print(x)\n"
        assert not matching(source, "DEAD_STORE")
        assert not matching(source, "UNUSED_VARIABLE")

    def test_for_iterable_is_read(self):
        source = "def f():\n    xs = [1, 2]\n    for x in xs:\n        print(x)\n"
        assert not matching(source, "UNUSED_VARIABLE")

    def test_unreachable_read_does_not_make_variable_used(self):
        source = "def f():\n    x = 5\n    return 0\n    print(x)\n"
        assert rule_lines(source, "UNUSED_VARIABLE") == [2]

    def test_conditional_overwrite_keeps_original_value_live(self):
        source = "def f(flag):\n    x = 1\n    if flag:\n        x = 2\n    return x\n"
        assert not matching(source, "DEAD_STORE")

    def test_delete_before_reassignment_is_dead_store(self):
        source = "def f():\n    x = 5\n    del x\n    x = 6\n    return x\n"
        assert rule_lines(source, "DEAD_STORE") == [2]

    def test_liveness_at_entry(self):
        cfg, forward, _ = report("def f(a):\n    x = a\n    return x\n")
        backward = analyze_liveness(cfg, forward)
        assert "a" in backward.ins[cfg.entry]
        assert "x" not in backward.ins[cfg.entry]

    def test_live_out_equals_successor_live_in_union(self):
        source = "def f(flag):\n    x = 3\n    if flag:\n        print(x)\n    return x\n"
        cfg, forward, _ = report(source)
        backward = analyze_liveness(cfg, forward)
        for block_id in forward.reachable:
            successors = [edge.target for edge in forward.edges[block_id]]
            expected = set()
            for successor in successors:
                expected.update(backward.ins[successor])
            assert set(backward.outs[block_id]) == expected

    def test_repeated_analysis_is_deterministic(self):
        source = "def f(flag):\n    x = 1\n    if flag:\n        x = 2\n    return x\n"
        first = [(d.rule, d.line, d.message) for d in issues(source)]
        second = [(d.rule, d.line, d.message) for d in issues(source)]
        assert first == second
