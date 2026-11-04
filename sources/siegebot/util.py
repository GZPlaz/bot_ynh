import random

from .defaults import ATTACKERS, DEFENDERS


def fill(template, **kw):
    """Safe placeholder replacement ({user}, {mention}, {server}, {args}, {target}, {op}...)."""
    kw.setdefault("op", random.choice(ATTACKERS + DEFENDERS))
    out = str(template)
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def chance(p):
    return random.random() < max(0.0, min(1.0, p))


def spongebob(text):
    return "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(text))
