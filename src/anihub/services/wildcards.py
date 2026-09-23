"""Wildcards: `__name__` in a prompt is replaced with one random entry from the user's own list called `name`, a
fresh pick every time -- including once per picture within the same batch (services/generation.py resolves it
separately for each Forge call it makes), not just once per click of Generate. Lives entirely in AniHUB: unlike
ADetailer/ControlNet/Forge Couple this needs no Forge extension at all, since the substitution happens on the
prompt text before it is ever sent."""
from __future__ import annotations

import random
import re

PLACEHOLDER = re.compile(r"__([^_\s]+(?:[ _-][^_\s]+)*)__")


def resolve(text: str, lists: dict[str, list[str]], rng: random.Random | None = None) -> str:
    """A placeholder whose name has no list, or an empty list, is left exactly as typed -- so a typo does not
    silently vanish into an empty string."""
    if not text or not lists:
        return text
    picker = rng or random
    lookup = {name.strip().lower(): choices for name, choices in lists.items() if choices}

    def sub(match: re.Match) -> str:
        choices = lookup.get(match.group(1).strip().lower())
        return str(picker.choice(choices)) if choices else match.group(0)

    return PLACEHOLDER.sub(sub, text)
