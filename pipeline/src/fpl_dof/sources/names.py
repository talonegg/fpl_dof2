"""Name normalisation, shared by every source.

Sources disagree about people. One writes the legal name, another the playing name; accents survive
in one and not the next; a suffix like "Jr" appears on a whim. Normalisation is what makes the
deterministic tier of entity resolution possible at all, and it lives here rather than in an
adapter because two adapters normalising differently would produce two identities for one player —
the failure this whole module exists to prevent.

Deliberately conservative. Normalisation may drop punctuation and accents; it may never drop a
name part, because "Rodrigo" and "Rodri" are two footballers and the day they play for the same
club is the day a clever rule becomes an invisible bug.
"""

from __future__ import annotations

import re
import unicodedata

#: Honorifics and generational suffixes that carry no identity. Kept short on purpose.
_SUFFIXES = frozenset({"jr", "jnr", "junior", "sr", "snr", "senior", "ii", "iii", "iv"})

_NON_NAME = re.compile(r"[^a-z0-9\s]+")
_SPACES = re.compile(r"\s+")


#: Letters that are not accented forms of anything and therefore survive decomposition unchanged.
#: Đorđe Petrović is the reason this table exists: one source writes the stroked D and another
#: writes a plain one, decomposition leaves the first as an unrelated character, and the two names
#: never meet.
_TRANSLITERATIONS = str.maketrans(
    {
        "Đ": "D",
        "đ": "d",
        "Ð": "D",
        "ð": "d",
        "Ø": "O",
        "ø": "o",
        "Ł": "L",
        "ł": "l",
        "Þ": "Th",
        "þ": "th",
        "ß": "ss",
        "Æ": "Ae",
        "æ": "ae",
        "Œ": "Oe",
        "œ": "oe",
        "ı": "i",  # noqa: RUF001 - the dotless i, deliberately: it decomposes to nothing
    }
)


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.translate(_TRANSLITERATIONS))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalise(value: str) -> str:
    """Lowercase, unaccented, punctuation-free, single-spaced, without generational suffixes."""
    folded = _NON_NAME.sub(" ", strip_accents(value).lower())
    parts = [part for part in _SPACES.split(folded) if part and part not in _SUFFIXES]
    return " ".join(parts)


def tokens(value: str) -> frozenset[str]:
    """The normalised name as an unordered set of parts.

    Unordered because sources reverse given and family names freely, and a set comparison is what
    makes "Son Heung-min" and "Heung-Min Son" the same person without a special case for each.
    """
    return frozenset(normalise(value).split())


def token_set_ratio(left: str, right: str) -> float:
    """Similarity in [0, 1] over normalised name tokens.

    Containment rather than overlap: the score is the shared tokens as a fraction of the *shorter*
    name, so one name being a subset of the other scores 1.0. That is deliberate, because the
    disagreement between these sources is almost always a missing name part rather than a typo —
    one publishes "Ezri Konsa" and another "Ezri Konsa Ngoyo" — and a symmetric measure like
    Jaccard scores that pair 0.67 and refuses a match that is obviously right.

    The obvious objection is that it also scores "Gabriel" against "Gabriel Jesus" at 1.0. That is
    handled where it should be: within a club, a candidate must beat its runner-up by a margin, so
    two plausible Gabriels resolve to *nothing* rather than to a coin flip. Scoring generously and
    refusing ambiguity is safer than scoring strictly and accepting whatever survives.

    Standard library only. A fuzzy-matching dependency buys finer scores on a problem this project
    deliberately solves by refusing close calls.
    """
    left_tokens, right_tokens = tokens(left), tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    shared = left_tokens & right_tokens
    if not shared:
        return 0.0
    return len(shared) / min(len(left_tokens), len(right_tokens))


def team_key(value: str) -> str:
    """A club name reduced to something two sources can agree on.

    Club naming is where sources are gratuitously different — "Wolverhampton Wanderers", "Wolves",
    "Wolverhampton". Dropping the generic suffixes leaves the distinguishing part, which is the
    part that is actually stable.
    """
    generic = {"fc", "afc", "united", "city", "town", "wanderers", "hotspur", "albion", "and"}
    parts = [part for part in normalise(value).split() if part not in generic]
    return " ".join(parts) or normalise(value)


__all__ = ["normalise", "strip_accents", "team_key", "token_set_ratio", "tokens"]
