import ast
import operator
from dataclasses import dataclass
from collections import deque

from .cfg import CFG


UNKNOWN = object()

OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


@dataclass
class State:
    defined: frozenset[str]
    constants: dict[str, object]


@dataclass
class AnalysisResult:
    ins: dict[int, State | None]
    outs: dict[int, State | None]
    edges: dict[int, list]
    reachable: set[int]


def merge(states):
    defined = set(states[0].defined)

    for state in states[1:]:
        defined &= state.defined

    constants = {
        name: value
        for name, value in states[0].constants.items()
        if all(
            state.constants.get(name, UNKNOWN) == value
            for state in states[1:]
        )
    }

    return State(frozenset(defined), constants)


def eval_expr(node, constants):
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        return constants.get(node.id, UNKNOWN)

    if isinstance(node, ast.BinOp):
        left = eval_expr(node.left, constants)
        right = eval_expr(node.right, constants)

        if left is UNKNOWN or right is UNKNOWN:
            return UNKNOWN

        fn = OPS.get(type(node.op))

        if fn:
            try:
                return fn(left, right)
            except Exception:
                pass

    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left = eval_expr(node.left, constants)
        right = eval_expr(node.comparators[0], constants)

        if left is UNKNOWN or right is UNKNOWN:
            return UNKNOWN

        fn = OPS.get(type(node.ops[0]))

        if fn:
            try:
                return fn(left, right)
            except Exception:
                pass

    if isinstance(node, ast.UnaryOp):
        value = eval_expr(node.operand, constants)

        if value is UNKNOWN:
            return UNKNOWN

        try:
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return +value
            if isinstance(node.op, ast.Not):
                return not value
        except Exception:
            pass

    return UNKNOWN


def transfer(stmt, state):
    defined = set(state.defined)
    constants = dict(state.constants)

    if isinstance(stmt, ast.Assign):
        if (
            len(stmt.targets) != 1
            or not isinstance(stmt.targets[0], ast.Name)
        ):
            return state

        name = stmt.targets[0].id
        value = eval_expr(stmt.value, constants)

        defined.add(name)

        if value is UNKNOWN:
            constants.pop(name, None)
        else:
            constants[name] = value

    return State(frozenset(defined), constants)


def transfer_block(block, state):
    for stmt in block.statements:
        state = transfer(stmt, state)

    return state


def active_edges(block, state):
    if block.condition is None:
        return block.edges

    value = eval_expr(
        block.condition,
        state.constants,
    )

    if value is UNKNOWN:
        return block.edges

    truth = bool(value)

    return [
        edge
        for edge in block.edges
        if edge.truth is None
        or edge.truth == truth
    ]


def analyze_cfg(cfg: CFG, parameters=()):
    boundary = State(
        frozenset(parameters),
        {},
    )

    ins = {
        block_id: None
        for block_id in cfg.blocks
    }

    outs = {
        block_id: None
        for block_id in cfg.blocks
    }

    edges = {
        block_id: []
        for block_id in cfg.blocks
    }

    ins[cfg.entry] = boundary

    worklist = deque([cfg.entry])
    queued = {cfg.entry}

    while worklist:
        block_id = worklist.popleft()
        queued.remove(block_id)

        block = cfg.blocks[block_id]

        if block_id == cfg.entry:
            new_in = boundary

        else:
            incoming = [
                outs[pred]
                for pred, pred_edges in edges.items()
                if outs[pred] is not None
                and any(
                    edge.target == block_id
                    for edge in pred_edges
                )
            ]

            new_in = (
                merge(incoming)
                if incoming
                else None
            )

        old_out = outs[block_id]
        old_edges = edges[block_id]

        ins[block_id] = new_in

        if new_in is None:
            new_out = None
            new_edges = []

        else:
            new_out = transfer_block(
                block,
                new_in,
            )

            new_edges = active_edges(
                block,
                new_out,
            )

        outs[block_id] = new_out
        edges[block_id] = new_edges

        if (
            new_out != old_out
            or new_edges != old_edges
        ):
            affected = {
                edge.target
                for edge in old_edges
            } | {
                edge.target
                for edge in new_edges
            }

            for successor in affected:
                if successor not in queued:
                    worklist.append(successor)
                    queued.add(successor)

    reachable = {
        block_id
        for block_id, state in ins.items()
        if state is not None
    }

    return AnalysisResult(
        ins=ins,
        outs=outs,
        edges=edges,
        reachable=reachable,
    )