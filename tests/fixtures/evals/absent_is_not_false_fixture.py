def must_flag(d, rec):
    if d.get("enabled"):  # FLAG: absent and False collapse
        pass
    n = sum(r.get("product_change") for r in rec)  # FLAG: E-033 exactly
    return d.get("a") and d.get("b"), n  # FLAG x2: boolean operands


def must_not_flag(d, rec):
    if d.get("enabled", False):  # explicit default
        pass
    t = str(d.get("tier") or "").strip()  # or-default
    if d.get("mode") == "fast":  # comparison
        pass
    if d.get("x") is None:  # comparison
        pass
    return t


def e038_shape(d, tool_list):
    if "Agent" not in tool_list(
        d.get("tools")
    ):  # FLAG: nested in a call inside a compare
        return 1
    return 0
