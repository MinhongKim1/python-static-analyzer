import argparse
import ast
from pathlib import Path

from .analysis import analyze_cfg
from .cfg import CFGBuilder, format_cfg
from .diagnostics import diagnose


def analyze_file(filename, show_cfg=False):
    path = Path(filename)
    source = path.read_text()

    tree = ast.parse(
        source,
        filename=str(path),
    )

    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    ]

    if not functions:
        functions = [tree]

    diagnostics = []

    for function in functions:
        cfg = CFGBuilder().build(function)

        parameters = ()

        if isinstance(function, ast.FunctionDef):
            parameters = tuple(
                arg.arg
                for arg in function.args.args
            )

        result = analyze_cfg(
            cfg,
            parameters,
        )

        diagnostics.extend(
            diagnose(
                cfg,
                result,
                parameters,
                report_liveness=isinstance(function, ast.FunctionDef),
            )
        )

        if show_cfg:
            name = (
                function.name
                if isinstance(
                    function,
                    ast.FunctionDef,
                )
                else "<module>"
            )

            print(f"=== CFG: {name} ===")
            print(format_cfg(cfg))
            print()

    return diagnostics


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("file")

    parser.add_argument(
        "--cfg",
        action="store_true",
    )

    args = parser.parse_args()

    try:
        diagnostics = analyze_file(
            args.file,
            args.cfg,
        )

    except (SyntaxError, ValueError) as error:
        print(
            f"{args.file}: error: {error}"
        )

        raise SystemExit(1)

    for diagnostic in diagnostics:
        print(
            f"{args.file}:"
            f"{diagnostic.line}:"
            f"{diagnostic.column} "
            f"{diagnostic.rule} "
            f"{diagnostic.message}"
        )

        if diagnostic.path:
            print("  Counterexample path:")

            for step in diagnostic.path:
                print(f"    {step}")

        print()

    print(
        f"{len(diagnostics)} issue(s) found"
    )


if __name__ == "__main__":
    main()