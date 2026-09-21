"""Age modes (12+ / 16+ / 18+) and the tag filter that goes with them.

- 12+  : content ratings 'general' only, and every tag of the 16+ and 18+ lists is hidden.
- 16+  : ratings up to 'questionable'; breasts, swimwear and the like are allowed, everything of the 18+ list is hidden.
- 18+  : no built-in restrictions.
The mode's tags ("locked" tags) are shown in Settings but cannot be edited; the user's own filter ("custom" tags) is added on top.
A tag entry ending with * is a prefix ("guro*" hides guro, guro_hentai...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from anihub.core.config import Config

MODES = ("12", "16", "18")
DEFAULT_MODE = "12"
RATINGS_BY_MODE = {
    "12": ["general"],
    "16": ["general", "sensitive", "questionable"],
    "18": ["general", "sensitive", "questionable", "explicit"],
}

# Hidden at 12+ and 16+: explicit sexual content, exposed genitals and nipples, fetishes, violence at its worst.
TAGS_18 = """
nsfw rating:explicit rating:questionable hentai uncensored censored mosaic_censoring bar_censor censored_nipples
sex sexual_intercourse vaginal anal oral fellatio cunnilingus deepthroat irrumatio footjob handjob paizuri titfuck breast_sucking
group_sex threesome orgy gangbang double_penetration sex_toy vibrator dildo masturbation fingering fisting
penis erection testicles futanari pussy vagina clitoris labia anus pubic_hair spread_pussy spread_anus spread_legs pussy_juice
nipples areolae puffy_nipples inverted_nipples nipple_slip breast_slip breasts_out bare_breasts exposed_breasts
topless nude completely_nude naked nude_cover naked_apron bottomless no_panties no_bra nudity
cum cumshot cum_on_body cum_on_breasts cum_on_face cum_in_pussy cum_in_mouth creampie ejaculation bukkake facial pregnant_sex
orgasm ahegao rolling_eyes_ahegao clothed_sex panties_aside panty_pull bikini_pull
rape molestation sexual_assault non-consensual bondage bdsm shibari bdsm_gear collar_and_leash femdom maledom
tentacles tentacle_sex bestiality zoophilia incest 
guro gore dismemberment decapitation snuff necrophilia scat urine watersports vore
loli lolicon shota shotacon toddlercon child_porn
""".split()

# Hidden at 12+ only: allowed from 16+ (the user's tier: "16+ gives access to breasts").
TAGS_16 = """
breasts large_breasts huge_breasts gigantic_breasts medium_breasts small_breasts flat_chest_grab breast_press breast_grab
breast_hold breast_squeeze cleavage underboob sideboob backboob cleavage_cutout large_areolae
bikini micro_bikini string_bikini sling_bikini swimsuit lingerie underwear panties bra thong g-string panty_shot pantyshot upskirt
cameltoe wet_clothes see-through see-through_silhouette wet_shirt sexually_suggestive seductive_smile bedroom_eyes
ass huge_ass butt_crack thighs_together shirtless naked_shirt naked_towel towel_only 
pole_dance stripper heart_pasties pasties
""".split()


def norm(tag: str) -> str:
    return re.sub(r"\s+", "_", tag.strip().lower())


def locked_tags(mode: str) -> list[str]:
    """The tags a mode hides by itself, sorted."""
    if mode == "12":
        return sorted({norm(t) for t in TAGS_16 + TAGS_18})
    if mode == "16":
        return sorted({norm(t) for t in TAGS_18})
    return []


def parse_tags(text: str) -> list[str]:
    """User input 'a, b_c  d*' -> ['a', 'b_c', 'd*'] (spaces and commas both separate; duplicates dropped)."""
    seen: dict[str, None] = {}
    for part in re.split(r"[\s,;]+", text or ""):
        t = norm(part)
        if t:
            seen.setdefault(t, None)
    return list(seen)


def mode_of(cfg: Config) -> str:
    """The current mode; older configs (only 'ratings.allowed') are translated once."""
    mode = str(cfg.get("age.mode", "") or "")
    if mode in MODES:
        return mode
    allowed = set(cfg.get("ratings.allowed", ["general"]))
    if "explicit" in allowed:
        return "18"
    if allowed & {"sensitive", "questionable"}:
        return "16"
    return DEFAULT_MODE


def apply_mode(cfg: Config, mode: str, save: bool = True) -> None:
    """Switch the mode: the content ratings follow it, and the locked tags follow automatically (they are computed)."""
    if mode not in MODES:
        raise ValueError(mode)
    cfg.set("age.mode", mode, save=False)
    cfg.set("ratings.allowed", list(RATINGS_BY_MODE[mode]), save=False)
    if save:
        cfg.save()


def custom_tags(cfg: Config) -> list[str]:
    return parse_tags(" ".join(cfg.get("filter.custom_tags", []) or []))


@dataclass(frozen=True)
class Blocker:
    exact: frozenset[str]
    prefixes: tuple[str, ...]

    @classmethod
    def from_tags(cls, tags: list[str]) -> "Blocker":
        exact = {t for t in tags if not t.endswith("*")}
        return cls(frozenset(exact), tuple(sorted({t[:-1] for t in tags if t.endswith("*") and len(t) > 1})))

    def blocks(self, tag: str) -> bool:
        t = norm(tag)
        return t in self.exact or any(t.startswith(p) for p in self.prefixes)

    def blocked_in(self, tags) -> bool:
        return any(self.blocks(t) for t in tags)

    def __bool__(self) -> bool:
        return bool(self.exact or self.prefixes)


def blocker_for(cfg: Config) -> Blocker:
    return Blocker.from_tags(locked_tags(mode_of(cfg)) + custom_tags(cfg))
