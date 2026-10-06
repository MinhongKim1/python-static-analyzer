import ast
from collections import deque
from dataclasses import dataclass

from .analysis import AnalysisResult, transfer
from .cfg import CFG


@dataclass(frozen=True)
class Diagnostic:
    line: int
    column: int
    rule: str
    message: str
    path: tuple[str, ...] = ()


def read_names(node):
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
        and isinstance(child.ctx, ast.Load)
    }


def assigns(stmt, name):
    return (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
        and stmt.targets[0].id == name
    )


def counterexample_path(
    cfg,
    edges,
    variable,
    target_block,
    target_node,
    parameters=(),
):
    if variable in parameters:
        return ()

    queue = deque([
        (
            cfg.entry,
            (f"B{cfg.entry}: entry",),
        )
    ])

    visited = set()

    while queue:
        block_id, path = queue.popleft()

        if block_id in visited:
            continue

        visited.add(block_id)

        block = cfg.blocks[block_id]

        for stmt in block.statements:
            if (
                block_id == target_block
                and stmt is target_node
            ):
                return path + (
                    f"B{block_id}: {ast.unparse(stmt)}",
                )

            if assigns(stmt, variable):
                break

        else:
            if (
                block_id == target_block
                and block.condition is target_node
            ):
                return path + (
                    f"B{block_id}: evaluate "
                    f"{ast.unparse(target_node)}",
                )

            for edge in edges[block_id]:
                description = (
                    f"B{block_id} -> B{edge.target}"
                )

                if (
                    block.condition is not None
                    and edge.truth is not None
                ):
                    description += (
                        f": {ast.unparse(block.condition)} "
                        f"is {str(edge.truth).lower()}"
                    )

                queue.append(
                    (
                        edge.target,
                        path + (description,),
                    )
                )

    return ()


def diagnose(
    cfg: CFG,
    result: AnalysisResult,
    parameters=(),
):
    diagnostics = []

    for block_id in sorted(result.reachable):
        block = cfg.blocks[block_id]
        state = result.ins[block_id]

        for stmt in block.statements:
            for name in sorted(read_names(stmt)):
                if name not in state.defined:
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
                if name not in state.defined:
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

    return sorted(
        diagnostics,
        key=lambda d: (
            d.line,
            d.column,
            d.rule,
        ),
    )