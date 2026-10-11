import ast
from collections import deque
from dataclasses import dataclass
from .cfg import CFG
from .analysis import AnalysisResult


def reads(node):
    if node is None:
        return set()
    result = {n.id for n in ast.walk(node)
              if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        result.add(node.target.id)
    return result


def writes(stmt):
    if isinstance(stmt, ast.Assign):
        return {target.id for target in stmt.targets}
    if isinstance(stmt, ast.AnnAssign):
        return {stmt.target.id} if stmt.value is not None else set()
    if isinstance(stmt, ast.AugAssign):
        return {stmt.target.id}
    if isinstance(stmt, ast.Delete):
        return {target.id for target in stmt.targets}
    return set()


def backwards_stmt(stmt, live):
    return (live - writes(stmt)) | reads(stmt)


def backwards_block(block, live_out):
    live = set(live_out)
    if block.condition is not None:
        live |= reads(block.condition)
    for stmt in reversed(block.statements):
        live = backwards_stmt(stmt, live)
    live -= set(block.writes_unknown)
    return frozenset(live)


@dataclass
class LivenessResult:
    ins: dict[int, frozenset[str]]
    outs: dict[int, frozenset[str]]


def analyze_liveness(cfg: CFG, result: AnalysisResult):
    reachable = result.reachable
    ins = {bid: frozenset() for bid in cfg.blocks}
    outs = {bid: frozenset() for bid in cfg.blocks}
    predecessors = {bid: set() for bid in cfg.blocks}
    for bid in reachable:
        for edge in result.edges[bid]:
            if edge.target in reachable:
                predecessors[edge.target].add(bid)

    queue = deque(sorted(reachable, reverse=True))
    queued = set(queue)
    while queue:
        bid = queue.popleft()
        queued.remove(bid)
        out = frozenset().union(*(
            ins[e.target] for e in result.edges[bid]
            if e.target in reachable
        ))
        new_in = backwards_block(cfg.blocks[bid], out)
        if out != outs[bid] or new_in != ins[bid]:
            outs[bid] = out
            ins[bid] = new_in
            for pred in predecessors[bid]:
                if pred not in queued:
                    queue.append(pred)
                    queued.add(pred)
    return LivenessResult(ins, outs)


def find_dead_stores(cfg: CFG, result: AnalysisResult):
    live = analyze_liveness(cfg, result)
    all_reads = set()
    assignments = []
    for bid in sorted(result.reachable):
        block = cfg.blocks[bid]
        if block.condition is not None:
            all_reads |= reads(block.condition)
        for stmt in block.statements:
            all_reads |= reads(stmt)
            if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for name in writes(stmt):
                    assignments.append((name, stmt))

    unused = {}
    for name, stmt in assignments:
        if name not in all_reads and not name.startswith('_'):
            old = unused.get(name)
            if old is None or (stmt.lineno, stmt.col_offset) < (old.lineno, old.col_offset):
                unused[name] = stmt
    issues = [
        (stmt.lineno, stmt.col_offset + 1, 'UNUSED_VARIABLE',
         f"'{name}' is assigned but never read")
        for name, stmt in unused.items()
    ]

    for bid in sorted(result.reachable):
        block = cfg.blocks[bid]
        at = set(live.outs[bid])
        if block.condition is not None:
            at |= reads(block.condition)
        for stmt in reversed(block.statements):
            if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for name in sorted(writes(stmt)):
                    if name not in at and name not in unused and not name.startswith('_'):
                        issues.append((stmt.lineno, stmt.col_offset + 1,
                                       'DEAD_STORE',
                                       f"value assigned to '{name}' is never read"))
            at = backwards_stmt(stmt, at)
    return sorted(set(issues))