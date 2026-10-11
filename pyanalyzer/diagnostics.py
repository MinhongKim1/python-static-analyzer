import ast
import builtins
from collections import deque
from dataclasses import dataclass

from .analysis import AnalysisResult, transfer, State, enter_block
from .cfg import CFG
from .liveness import find_dead_stores


@dataclass(frozen=True)
class Diagnostic:
    line: int
    column: int
    rule: str
    message: str
    path: tuple[str, ...] = ()


def read_names(node):
    names = {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }
    if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        names.add(node.target.id)
    return names

def counterexample_path(
    cfg, edges, variable, target_block, target_node, parameters=()
):
    initial_defined = variable in parameters
    queue = deque([(cfg.entry, initial_defined, (f"B{cfg.entry}: entry",))])
    visited = set()

    while queue:
        block_id, is_defined, path = queue.popleft()
        key = (block_id, is_defined)
        if key in visited:
            continue
        visited.add(key)
        block = cfg.blocks[block_id]
        if variable in block.writes_unknown:
            is_defined = True

        for stmt in block.statements:
            if block_id == target_block and stmt is target_node and not is_defined:
                return path + (f"B{block_id}: {ast.unparse(stmt)}",)
            # Use the same transfer semantics as the main analysis.
            previous = State(frozenset([variable]) if is_defined else frozenset(), {})
            is_defined = variable in transfer(stmt, previous).defined

        if block_id == target_block and block.condition is target_node and not is_defined:
            return path + (f"B{block_id}: evaluate {ast.unparse(target_node)}",)

        for edge in edges[block_id]:
            description = f"B{block_id} -> B{edge.target}"
            if block.condition is not None and edge.truth is not None:
                if block.iteration_condition:
                    description += ": next item" if edge.truth else ": exhausted"
                else:
                    description += (
                        f": {ast.unparse(block.condition)} is {str(edge.truth).lower()}"
                    )
            queue.append((edge.target, is_defined, path + (description,)))

    return ()

def diagnose(
    cfg: CFG,
    result: AnalysisResult,
    parameters=(),
    report_liveness=True,
):
    diagnostics = []

    for block_id in sorted(result.reachable):
        block = cfg.blocks[block_id]
        state = enter_block(block, result.ins[block_id])

        for stmt in block.statements:
            for name in sorted(read_names(stmt)):
                if name not in state.defined and name not in dir(builtins):
                    path = counterexample_path(
                        cfg,
                        result.edges,
                        name,
                        block_id,
                        stmt,
                        parameters,
                    )

                    diagnostics.append(
                        Diagnostic(
                            stmt.lineno,
                            stmt.col_offset + 1,
                            "POSSIBLY_UNDEFINED",
                            f"'{name}' may be undefined",
                            path,
                        )
                    )

            state = transfer(stmt, state)

        if block.condition is not None:
            for name in sorted(
                read_names(block.condition)
            ):
                if name not in state.defined and name not in dir(builtins):
                    path = counterexample_path(
                        cfg,
                        result.edges,
                        name,
                        block_id,
                        block.condition,
                        parameters,
                    )

                    diagnostics.append(
                        Diagnostic(
                            block.condition.lineno,
                            block.condition.col_offset + 1,
                            "POSSIBLY_UNDEFINED",
                            f"'{name}' may be undefined",
                            path,
                        )
                    )

    for block_id, block in cfg.blocks.items():
        if block_id in result.reachable:
            continue

        node = (
            block.statements[0]
            if block.statements
            else block.condition
        )

        if node is not None:
            diagnostics.append(
                Diagnostic(
                    node.lineno,
                    node.col_offset + 1,
                    "UNREACHABLE",
                    "code is unreachable",
                )
            )

    if report_liveness:
        for line, column, rule, message in find_dead_stores(cfg, result):
            diagnostics.append(Diagnostic(line, column, rule, message))

    return sorted(
        diagnostics,
        key=lambda d: (
            d.line,
            d.column,
            d.rule,
        ),
    )