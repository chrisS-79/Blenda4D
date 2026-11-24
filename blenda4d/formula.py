# SPDX-License-Identifier: GPL-3.0-or-later
"""A typed formula ("sin((id/count+t)*360)") turned into Geometry Nodes math, for the Formula effector and field.

Only arithmetic, the functions in FUNCS and the variables the caller gives are allowed: the text is parsed, never run.
Trigonometry works in degrees (sin(90) = 1) unless the caller asks for radians."""
import ast
import math

from .primitives import _math

DEG = math.pi / 180.0


def _unary(op):
    return lambda nodes, links, a: _math(nodes, op, a, None, links)


def _binary(op):
    return lambda nodes, links, a, b: _math(nodes, op, a, b, links)


def _deg_in(op):
    return lambda nodes, links, a, deg=True: _math(nodes, op, _math(nodes, "MULTIPLY", a, DEG, links) if deg else a, None, links)


def _deg_out(op):
    return lambda nodes, links, a, deg=True: (_math(nodes, "MULTIPLY", _math(nodes, op, a, None, links), 1.0 / DEG, links)
                                              if deg else _math(nodes, op, a, None, links))


FUNCS = {
    "sin": (_deg_in("SINE"), 1, True), "cos": (_deg_in("COSINE"), 1, True), "tan": (_deg_in("TANGENT"), 1, True),
    "asin": (_deg_out("ARCSINE"), 1, True), "acos": (_deg_out("ARCCOSINE"), 1, True), "atan": (_deg_out("ARCTANGENT"), 1, True),
    "sinh": (_unary("SINH"), 1, False), "cosh": (_unary("COSH"), 1, False), "tanh": (_unary("TANH"), 1, False),
    "sqrt": (_unary("SQRT"), 1, False), "abs": (_unary("ABSOLUTE"), 1, False), "exp": (_unary("EXPONENT"), 1, False),
    "ln": (lambda n, l, a: _math(n, "LOGARITHM", a, math.e, l), 1, False),
    "log": (lambda n, l, a: _math(n, "LOGARITHM", a, 10.0, l), 1, False),
    "log10": (lambda n, l, a: _math(n, "LOGARITHM", a, 10.0, l), 1, False),
    "floor": (_unary("FLOOR"), 1, False), "ceil": (_unary("CEIL"), 1, False), "round": (_unary("ROUND"), 1, False),
    "trunc": (_unary("TRUNC"), 1, False), "frac": (_unary("FRACT"), 1, False), "sign": (_unary("SIGN"), 1, False),
    "min": (_binary("MINIMUM"), 2, False), "max": (_binary("MAXIMUM"), 2, False), "pow": (_binary("POWER"), 2, False),
    "mod": (_binary("FLOORED_MODULO"), 2, False), "atan2": (None, 2, True),
    "clamp": (None, 3, False),
}
CONSTS = {"pi": math.pi, "e": math.e}


class FormulaError(ValueError):
    pass


def check(text, variables):
    """The problem with a formula, in plain words, or None when it is fine."""
    try:
        _walk(None, None, ast.parse(_py(text), mode="eval").body, {v: 0.0 for v in variables}, True)
    except FormulaError as ex:
        return str(ex)
    except SyntaxError:
        return "The formula is not complete or has a typing mistake"
    return None


def _py(text):
    return text.replace("^", "**").strip() or "0"


def build(nodes, links, text, variables, degrees=True):
    """The formula's value as a socket (or a number); variables: name -> socket or number. A formula with a problem
    gives 0."""
    try:
        return _walk(nodes, links, ast.parse(_py(text), mode="eval").body, variables, False, degrees)
    except (FormulaError, SyntaxError):
        return 0.0


_OPS = {ast.Add: "ADD", ast.Sub: "SUBTRACT", ast.Mult: "MULTIPLY", ast.Div: "DIVIDE", ast.Pow: "POWER", ast.Mod: "FLOORED_MODULO"}
_CMP = {ast.Lt: "LESS_THAN", ast.Gt: "GREATER_THAN"}


def _walk(nodes, links, n, var, dry, deg=True):
    def go(x):
        return _walk(nodes, links, x, var, dry, deg)

    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return float(n.value)
    if isinstance(n, ast.Name):
        if n.id in var:
            return var[n.id]
        if n.id.lower() in CONSTS:
            return CONSTS[n.id.lower()]
        raise FormulaError(f"Unknown name: {n.id}")
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        v = go(n.operand)
        if isinstance(n.op, ast.UAdd):
            return v
        return -v if isinstance(v, float) else (0.0 if dry else _math(nodes, "MULTIPLY", v, -1.0, links))
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        a, b = go(n.left), go(n.right)
        if dry:
            return 0.0
        return _math(nodes, _OPS[type(n.op)], a, b, links)
    if isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in _CMP:
        a, b = go(n.left), go(n.comparators[0])
        return 0.0 if dry else _math(nodes, _CMP[type(n.ops[0])], a, b, links)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
        name = n.func.id.lower()
        if name not in FUNCS:
            raise FormulaError(f"Unknown function: {n.func.id}")
        fn, argc, trig = FUNCS[name]
        if len(n.args) != argc or n.keywords:
            raise FormulaError(f"{name} takes {argc} value{'s' if argc > 1 else ''}")
        args = [go(a) for a in n.args]
        if dry:
            return 0.0
        if name == "atan2":
            r = _math(nodes, "ARCTAN2", args[0], args[1], links)
            return _math(nodes, "MULTIPLY", r, 1.0 / DEG, links) if deg else r
        if name == "clamp":
            return _math(nodes, "MINIMUM", _math(nodes, "MAXIMUM", args[0], args[1], links), args[2], links)
        return fn(nodes, links, *args, deg) if trig else fn(nodes, links, *args)
    raise FormulaError("Only numbers, + - * / ^ %, brackets and the listed functions can be used")
