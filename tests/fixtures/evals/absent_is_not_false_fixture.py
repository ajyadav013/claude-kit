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


def waived_shapes(d):
    """Both waiver placements must suppress the flag.

    These are must-NOT-flag lines, so if the waiver mechanism breaks in either direction the
    control reports a false positive. Without them the mechanism had no control at all: it could
    have stopped recognising waivers entirely and the self-test would still have passed.
    """
    if d.get("trailing"):  # absent-ok: absence means off, which is the same as off
        pass
    # absent-ok: a reason too long to trail the statement goes directly above it, which is where
    # a reader looks anyway; placement is not what makes a waiver honest.
    if d.get("preceding"):
        pass


def e038_shape(d, tool_list):
    if "Agent" not in tool_list(
        d.get("tools")
    ):  # FLAG: nested in a call inside a compare
        return 1
    return 0
