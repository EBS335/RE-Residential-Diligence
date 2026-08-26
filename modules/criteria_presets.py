"""
Combinable criteria-preset building blocks for Site Finder's "Build a
Search" panel — Borough + Neighborhood + Strategy + Property Type + Risk,
each independently optional, combined into a criteria dict and fed
through the existing load_saved_criteria_into_widgets() reuse point (the
same one the Portfolio tab's "Re-run" action already uses for user-saved
searches).

Supersedes the earlier fixed-button THESIS_PRESETS design (3 named
one-click bundles) — redesigned per direct request into a set of
combinable category dimensions instead, so any combination of
Borough/Neighborhood/Strategy/Property-Type/Risk can be picked and
applied in one step.

NEIGHBORHOODS_BY_BOROUGH is a curated approximation: no live PLUTO field
in the bulk-search path maps a neighborhood name to search results (the
"nta" field only exists on the single-BBL zola_fetcher.py lookup, not
property_search.py's bulk normalization — confirmed by direct
investigation), so a neighborhood selection here works by filling the
existing "ZIP codes" criteria field with that neighborhood's known,
representative ZIP code(s) — not a precise boundary/polygon match.
"""

from modules.site_sourcing import (
    STRATEGY_GROUND_UP, STRATEGY_VACANT, STRATEGY_DEMOLITION, STRATEGY_CONVERSION,
)

# All 4 strategy values site_sourcing.classify_strategies() can assign —
# STRATEGY_GROUND_UP was previously defined but never exposed in the
# criteria form's own strategies multiselect; it's included here too so
# this panel's "Strategy" dimension is the complete, correct set.
STRATEGY_OPTIONS = [STRATEGY_GROUND_UP, STRATEGY_VACANT, STRATEGY_DEMOLITION, STRATEGY_CONVERSION]

# Borough -> neighborhood display name -> representative ZIP code(s).
NEIGHBORHOODS_BY_BOROUGH: dict[str, dict[str, list[str]]] = {
    "Manhattan": {
        "Upper East Side":   ["10021", "10028", "10065", "10075"],
        "Upper West Side":   ["10023", "10024", "10025"],
        "Harlem":            ["10026", "10027", "10030", "10037", "10039"],
        "Chelsea":           ["10001", "10011"],
        "Greenwich Village": ["10003", "10011", "10012"],
        "SoHo / Tribeca":    ["10012", "10013"],
        "Financial District": ["10004", "10005", "10006", "10038"],
        "Midtown":           ["10018", "10019", "10020", "10036"],
        "Washington Heights": ["10032", "10033", "10040"],
    },
    "Brooklyn": {
        "Williamsburg":       ["11211", "11249"],
        "Park Slope":         ["11215", "11217"],
        "Brooklyn Heights / DUMBO": ["11201"],
        "Bushwick":           ["11206", "11237"],
        "Bedford-Stuyvesant": ["11205", "11216", "11221", "11233"],
        "Crown Heights":      ["11213", "11225", "11238"],
        "Sunset Park":        ["11220", "11232"],
        "Bay Ridge":          ["11209"],
    },
    "Queens": {
        "Astoria":         ["11102", "11103", "11105", "11106"],
        "Long Island City": ["11101", "11109"],
        "Flushing":        ["11354", "11355"],
        "Jackson Heights": ["11372"],
        "Forest Hills":    ["11375"],
        "Jamaica":         ["11432", "11433", "11434"],
        "Ridgewood":       ["11385"],
        "Bayside":         ["11360", "11361"],
    },
    "Bronx": {
        "Mott Haven":  ["10454", "10455"],
        "Fordham":     ["10458", "10468"],
        "Riverdale":   ["10463", "10471"],
        "Pelham Bay":  ["10461", "10462"],
        "Concourse":   ["10451", "10452"],
        "Soundview":   ["10473"],
    },
    "Staten Island": {
        "St. George / Stapleton": ["10301", "10304"],
        "New Dorp":               ["10306"],
        "Tottenville":            ["10307"],
        "Great Kills":            ["10308"],
        "Port Richmond":          ["10302"],
    },
}


def neighborhoods_for_boroughs(boroughs: list[str] | None) -> list[str]:
    """Sorted, deduped neighborhood names available for the given
    boroughs — all neighborhoods across every borough if `boroughs` is
    empty/None (so the Neighborhood selector still has options before a
    Borough is chosen)."""
    keys = boroughs if boroughs else list(NEIGHBORHOODS_BY_BOROUGH.keys())
    names: set[str] = set()
    for b in keys:
        names.update(NEIGHBORHOODS_BY_BOROUGH.get(b, {}).keys())
    return sorted(names)


def build_criteria_from_selections(
    boroughs: list[str] | None = None,
    neighborhoods: list[str] | None = None,
    strategies: list[str] | None = None,
    property_types: list[str] | None = None,
    risk: str | None = None,
) -> dict:
    """
    Combine independently-optional category selections into a criteria
    dict shaped exactly like _render_criteria_form()'s own return value,
    ready for load_saved_criteria_into_widgets(). Any dimension left
    empty/None is simply OMITTED from the result (not set to an empty
    list/None value) — combining zero selections returns {}, and
    load_saved_criteria_into_widgets() already falls back to each
    widget's normal default for any key that's absent, so a partially
    combined selection behaves exactly like a partially-filled form.
    """
    criteria: dict = {}
    if boroughs:
        criteria["boroughs"] = list(boroughs)
    if neighborhoods:
        zips: set[str] = set()
        for borough_map in NEIGHBORHOODS_BY_BOROUGH.values():
            for name in neighborhoods:
                zips.update(borough_map.get(name, []))
        if zips:
            criteria["zip_codes"] = sorted(zips)
    if strategies:
        criteria["strategies"] = list(strategies)
    if property_types:
        criteria["property_types"] = list(property_types)
    if risk:
        criteria["risk"] = risk
    return criteria
