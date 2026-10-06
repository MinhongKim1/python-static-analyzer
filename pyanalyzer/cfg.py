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
        self.blocks[source].edges.append(
            Edge(target, truth)
        )

    def join(self, incoming):
        if not incoming:
            return self.new_block()

        if len(incoming) == 1:
            return incoming[0]

        block = self.new_block()

        for source in incoming:
            self.connect(source, block)

        return block

    def build(self, node: ast.FunctionDef | ast.Module):
        self.blocks = {}
        self.next_id = 0

        entry = self.new_block()

        body = node.body

        self.build_sequence(
            body,
            [entry],
            None,
            None,
        )

        return CFG(self.blocks, entry)

    def build_sequence(
        self,
        statements,
        incoming,
        break_target,
        continue_target,
    ):
        current = self.join(incoming)

        for stmt in statements:
            if isinstance(stmt, ast.If):
                self.blocks[current].condition = stmt.test

                true_block = self.new_block()
                false_block = self.new_block()

                self.connect(
                    current,
                    true_block,
                    True,
                )

                self.connect(
                    current,
                    false_block,
                    False,
                )

                true_exits = self.build_sequence(
                    stmt.body,
                    [true_block],
                    break_target,
                    continue_target,
                )

                if stmt.orelse:
                    false_exits = self.build_sequence(
                        stmt.orelse,
                        [false_block],
                        break_target,
                        continue_target,
                    )
                else:
                    false_exits = [false_block]

                current = self.join(
                    true_exits + false_exits
                )

            elif isinstance(stmt, ast.While):
                if stmt.orelse:
                    raise SyntaxError(
                        "while/else is not supported"
                    )

                condition = self.new_block()
                self.connect(current, condition)

                self.blocks[condition].condition = stmt.test

                body = self.new_block()
                after = self.new_block()

                self.connect(
                    condition,
                    body,
                    True,
                )

                self.connect(
                    condition,
                    after,
                    False,
                )

                body_exits = self.build_sequence(
                    stmt.body,
                    [body],
                    after,
                    condition,
                )

                for exit_block in body_exits:
                    self.connect(
                        exit_block,
                        condition,
                    )

                current = after

            elif isinstance(stmt, ast.Break):
                if break_target is None:
                    raise SyntaxError(
                        "break outside loop"
                    )

                self.connect(
                    current,
                    break_target,
                )

                current = self.new_block()

            elif isinstance(stmt, ast.Continue):
                if continue_target is None:
                    raise SyntaxError(
                        "continue outside loop"
                    )

                self.connect(
                    current,
                    continue_target,
                )

                current = self.new_block()

            elif isinstance(stmt, ast.Return):
                self.blocks[current].statements.append(
                    stmt
                )

                current = self.new_block()

            elif isinstance(stmt, ast.FunctionDef):
                raise SyntaxError(
                    "nested functions are not supported"
                )

            else:
                self.blocks[current].statements.append(
                    stmt
                )

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
            lines.append(
                f"  IF {ast.unparse(block.condition)}"
            )

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