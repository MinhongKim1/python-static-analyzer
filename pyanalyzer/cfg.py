import ast
from dataclasses import dataclass, field


@dataclass
class Edge:
    target: int
    truth: bool | None = None


@dataclass
class BasicBlock:
    id: int
    statements: list[ast.stmt] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    condition: ast.expr | None = None
    iteration_condition: bool = False
    writes_unknown: tuple[str, ...] = ()


@dataclass
class CFG:
    blocks: dict[int, BasicBlock]
    entry: int

    def predecessors(self, target: int):
        return [
            block.id
            for block in self.blocks.values()
            for edge in block.edges
            if edge.target == target
        ]


class CFGBuilder:
    def __init__(self):
        self.blocks: dict[int, BasicBlock] = {}
        self.next_id = 0

    def new_block(self):
        block = BasicBlock(self.next_id)
        self.blocks[block.id] = block
        self.next_id += 1
        return block.id

    def connect(self, source, target, truth=None):
        self.blocks[source].edges.append(Edge(target, truth))

    def join(self, incoming):
        if not incoming:
            return self.new_block()
        if len(incoming) == 1:
            return incoming[0]
        block = self.new_block()
        for source in incoming:
            self.connect(source, block)
        return block

    def validate_subset(self, node):
        allowed_statements = (
            ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete,
            ast.Expr, ast.Pass, ast.Return, ast.If, ast.While,
            ast.For, ast.Break, ast.Continue, ast.Raise,
        )
        for item in ast.walk(node):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item is not node:
                raise SyntaxError(f"nested function at line {item.lineno} is unsupported")
            if isinstance(item, ast.stmt) and item is not node:
                if not isinstance(item, allowed_statements):
                    raise SyntaxError(
                        f"unsupported {type(item).__name__} at line {item.lineno}"
                    )
            if isinstance(item, (ast.NamedExpr, ast.Yield, ast.YieldFrom, ast.Await)):
                raise SyntaxError(f"unsupported {type(item).__name__} at line {item.lineno}")
            if isinstance(item, ast.Assign):
                if not item.targets or not all(isinstance(t, ast.Name) for t in item.targets):
                    raise SyntaxError(f"only name assignment is supported (line {item.lineno})")
            if isinstance(item, (ast.AugAssign, ast.AnnAssign)):
                if not isinstance(item.target, ast.Name):
                    raise SyntaxError(f"only name targets are supported (line {item.lineno})")
            if isinstance(item, ast.Delete):
                if not all(isinstance(t, ast.Name) for t in item.targets):
                    raise SyntaxError(f"only name deletion is supported (line {item.lineno})")
            if isinstance(item, ast.For) and not isinstance(item.target, ast.Name):
                raise SyntaxError(f"only simple for-loop targets are supported (line {item.lineno})")
            if isinstance(item, ast.Raise) and item.exc is None:
                raise SyntaxError(f"bare raise at line {item.lineno} is unsupported")

    def build(self, node: ast.FunctionDef | ast.Module):
        self.validate_subset(node)
        self.blocks = {}
        self.next_id = 0
        entry = self.new_block()
        self.build_sequence(node.body, [entry], None, None)
        return CFG(self.blocks, entry)

    def build_sequence(self, statements, incoming, break_target, continue_target):
        current = self.join(incoming)
        for stmt in statements:
            if isinstance(stmt, ast.If):
                self.blocks[current].condition = stmt.test
                true_block = self.new_block()
                false_block = self.new_block()
                self.connect(current, true_block, True)
                self.connect(current, false_block, False)
                true_exits = self.build_sequence(
                    stmt.body, [true_block], break_target, continue_target
                )
                false_exits = self.build_sequence(
                    stmt.orelse, [false_block], break_target, continue_target
                ) if stmt.orelse else [false_block]
                current = self.join(true_exits + false_exits)

            elif isinstance(stmt, (ast.While, ast.For)):
                header = self.new_block()
                self.connect(current, header)
                is_for = isinstance(stmt, ast.For)
                self.blocks[header].condition = stmt.iter if is_for else stmt.test
                self.blocks[header].iteration_condition = is_for

                body = self.new_block()
                after = self.new_block()
                if is_for:
                    self.blocks[body].writes_unknown = (stmt.target.id,)
                self.connect(header, body, True)

                if stmt.orelse:
                    else_entry = self.new_block()
                    self.connect(header, else_entry, False)
                else:
                    else_entry = None
                    self.connect(header, after, False)

                body_exits = self.build_sequence(
                    stmt.body, [body], after, header
                )
                for exit_block in body_exits:
                    self.connect(exit_block, header)

                if stmt.orelse:
                    else_exits = self.build_sequence(
                        stmt.orelse, [else_entry], break_target, continue_target
                    )
                    for exit_block in else_exits:
                        self.connect(exit_block, after)
                current = after

            elif isinstance(stmt, ast.Break):
                if break_target is None:
                    raise SyntaxError('break outside loop')
                self.connect(current, break_target)
                current = self.new_block()

            elif isinstance(stmt, ast.Continue):
                if continue_target is None:
                    raise SyntaxError('continue outside loop')
                self.connect(current, continue_target)
                current = self.new_block()

            elif isinstance(stmt, (ast.Return, ast.Raise)):
                self.blocks[current].statements.append(stmt)
                current = self.new_block()

            else:
                self.blocks[current].statements.append(stmt)
        return [current]


def format_cfg(cfg: CFG):
    sections = []

    for block in cfg.blocks.values():
        lines = [f"B{block.id}:"]

        for stmt in block.statements:
            lines.append(
                "  " + ast.unparse(stmt)
            )

        if block.condition is not None:
            prefix = "ITERATE" if block.iteration_condition else "IF"
            lines.append(f"  {prefix} {ast.unparse(block.condition)}")
        if block.writes_unknown:
            lines.append(f"  BIND {', '.join(block.writes_unknown)} (unknown)")

        for edge in block.edges:
            label = ""

            if edge.truth is True:
                label = " [true]"

            elif edge.truth is False:
                label = " [false]"

            lines.append(
                f"  -> B{edge.target}{label}"
            )

        sections.append("\n".join(lines))

    return "\n\n".join(sections)