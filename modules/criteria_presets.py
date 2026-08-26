"""
Curated, code-defined Investment Criteria bundles — distinct from
user-saved searches (modules.portfolio_db.saved_searches, which persist
whatever criteria a USER built and named). These are developer-curated
starting points, versioned with the code, fed through the exact same
load_saved_criteria_into_widgets() reuse point the Portfolio tab's
"Re-run" button already uses for user-saved searches.
"""

THESIS_PRESETS: dict[str, dict] = {
    "Brooklyn Vacant Lot Play": {
        "boroughs": ["Brooklyn"], "property_types": ["Vacant Lot"],
        "min_far": 2.0, "strategies": ["Vacant / Underutilized"], "risk": "Moderate",
    },
    "Queens Underbuilt Multifamily": {
        "boroughs": ["Queens"], "property_types": ["Multifamily"],
        "min_units": 1, "max_units": 20, "risk": "Moderate",
    },
    "Manhattan Conversion Candidates": {
        "boroughs": ["Manhattan"],
        "strategies": ["Conversion / Redevelopment"], "risk": "High",
    },
}
