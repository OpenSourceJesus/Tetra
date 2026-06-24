#!/usr/bin/env python3
"""Translate JavaScript source to pure Python targeting the PyQt5 API."""

import sys

from pyjsparser import parse as parse_javascript

_state = {"alert_used": False}


def emit_node(node) -> list[str]:
    if node is None:
        return []

    node_type = node.get("type")

    if node_type == "Program":
        _state["alert_used"] = False
        lines: list[str] = []
        for child in node.get("body", []):
            lines.extend(emit_node(child))
        if _state["alert_used"]:
            lines.insert(0, "from PyQt5.QtWidgets import QMessageBox")
        return lines

    if node_type == "FunctionDeclaration":
        func_name = node["id"]["name"]
        params = ", ".join(p["name"] for p in node.get("params", []))
        body_lines: list[str] = []
        for child in node["body"]["body"]:
            body_lines.extend(emit_node(child))
        if not body_lines:
            body_lines = ["pass"]
        indented = "\n".join(f"    {line}" for line in body_lines)
        return [f"def {func_name}({params}):", indented]

    if node_type == "ExpressionStatement":
        return emit_node(node["expression"])

    if node_type == "CallExpression":
        callee = node["callee"]
        args = ", ".join(expr_text(arg) for arg in node.get("arguments", []))

        if callee["type"] == "Identifier" and callee["name"] == "alert":
            _state["alert_used"] = True
            return [f"QMessageBox.information(None, 'Alert', str({args}))"]

        callee_str = expr_text(callee)
        if callee_str in {"None", ""} or callee_str.startswith("None."):
            return []
        return [f"{callee_str}({args})"]

    if node_type == "AssignmentExpression":
        left = node["left"]
        right = expr_text(node["right"])
        left_str = expr_text(left)

        if left_str.startswith(("window.", "document.", "None.", "None")):
            return []

        if (
            left["type"] == "MemberExpression"
            and not left.get("computed")
            and left["property"].get("name") == "style"
        ):
            obj = expr_text(left["object"])
            if obj in {"None", ""} or obj.startswith("None."):
                return []
            return [f"{obj}.setStyleSheet({right})"]

        return [f"{left_str} = {right}"]

    if node_type == "BlockStatement":
        lines: list[str] = []
        for child in node.get("body", []):
            lines.extend(emit_node(child))
        return lines

    if node_type == "ReturnStatement":
        arg = node.get("argument")
        if arg is None:
            return ["return"]
        return [f"return {expr_text(arg)}"]

    if node_type == "VariableDeclaration":
        lines: list[str] = []
        for decl in node.get("declarations", []):
            name = decl["id"]["name"]
            init = decl.get("init")
            if init is not None:
                lines.append(f"{name} = {expr_text(init)}")
            else:
                lines.append(f"{name} = None")
        return lines

    return []


def expr_text(node) -> str:
    if node is None:
        return "None"

    node_type = node.get("type")

    if node_type == "Identifier":
        return node["name"]

    if node_type == "Literal":
        return repr(node["value"])

    if node_type == "MemberExpression":
        obj = expr_text(node["object"])
        if node.get("computed"):
            return f"{obj}[{expr_text(node['property'])}]"
        return f"{obj}.{node['property']['name']}"

    if node_type == "CallExpression":
        callee = node["callee"]
        args = ", ".join(expr_text(arg) for arg in node.get("arguments", []))
        return f"{expr_text(callee)}({args})"

    if node_type == "AssignmentExpression":
        return emit_node(node)[0]

    return "None"


def translate_javascript(js_code: str) -> str:
    js_ast = parse_javascript(js_code)
    return "\n".join(emit_node(js_ast))


def main():
    js_code = sys.stdin.read()
    if not js_code.strip():
        return

    try:
        print(translate_javascript(js_code))
    except Exception as exc:
        print(f"# Translation Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
