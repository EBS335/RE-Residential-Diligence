"""
Site Finder AI Diligence Agents — Phase 4.

Specialized single-purpose Claude agents that reason ONLY over data
already gathered by the app (PLUTO, zoning rules, ACRIS, market comps,
pipeline) for ONE selected property. Every agent is forced to return
structured JSON (via tool-use / function calling) rather than free text,
and every material finding must carry a source, a confidence level, and
whether it is verified (drawn from the data passed in) or estimated
(inferred by the model).

Agents do NOT independently browse the web — they synthesize/critique
the structured data the rest of Site Finder has already collected, plus
general NYC real-estate domain knowledge, and are explicitly instructed
to flag gaps rather than invent facts. This keeps the system auditable:
every claim traces back to either "from the data you gave me" (verified)
or "my inference, needs confirmation" (estimated).

Uses the same Claude model string ("claude-opus-4-6") as the existing
AI Market Summary feature in app.py for consistency.
"""

from __future__ import annotations
import json

_MODEL = "claude-opus-4-6"

AGENT_ORDER = [
    "property", "zoning", "market", "development",
    "financial", "risk", "investment_committee",
]

_FINDINGS_SCHEMA = {
    "name": "submit_findings",
    "description": "Submit structured research findings for this property.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "2-4 sentence overview"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "finding":    {"type": "string"},
                        "source":     {"type": "string", "description": "Which input dataset this came from, or 'model inference' if estimated"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "verified":   {"type": "boolean", "description": "True if directly supported by the data provided, false if inferred/estimated"},
                    },
                    "required": ["finding", "source", "confidence", "verified"],
                },
            },
        },
        "required": ["summary", "findings"],
    },
}

_IC_SCHEMA = {
    "name": "submit_ic_review",
    "description": "Submit the Investment Committee review and recommendation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "recommendation": {"type": "string", "enum": ["GO", "WATCH", "REJECT"]},
            "thesis":         {"type": "array", "items": {"type": "string"}, "description": "3-5 bullets: why this property"},
            "key_risks":      {"type": "array", "items": {"type": "string"}, "description": "5-10 risks"},
            "key_unknowns":   {"type": "array", "items": {"type": "string"}, "description": "Items requiring diligence"},
            "next_steps":     {"type": "array", "items": {"type": "string"}, "description": "Prioritized next diligence steps"},
        },
        "required": ["recommendation", "thesis", "key_risks", "key_unknowns", "next_steps"],
    },
}


def has_anthropic_key(api_key: str | None) -> bool:
    return bool(api_key and api_key.strip())


def _call_agent(system_prompt: str, user_prompt: str, api_key: str, schema: dict) -> dict:
    try:
        import anthropic
    except ImportError:
        return {"error": "Install the `anthropic` package to enable AI diligence agents: pip install anthropic"}

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=1200,
            system=system_prompt,
            tools=[schema],
            tool_choice={"type": "tool", "name": schema["name"]},
            messages=[{"role": "user", "content": user_prompt}],
        )
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use":
                return dict(block.input)
        return {"error": "Agent did not return structured output"}
    except Exception as exc:
        return {"error": str(exc)}


def _property_context(prop: dict) -> str:
    """Serialize the property's already-collected data for agent prompts."""
    ds = prop.get("deal_score", {})
    opp = prop.get("opportunity", {})
    ctx = {
        "address": prop.get("address"), "bbl": prop.get("bbl"), "borough": prop.get("borough"),
        "lot_sf": prop.get("lot_sf"), "bldg_sf": prop.get("bldg_sf"),
        "year_built": prop.get("year_built"), "zoning_dist": prop.get("zoning_dist"),
        "far_built": prop.get("far_built"), "far_max": prop.get("far_max"),
        "unused_far_pct": prop.get("unused_far_pct"),
        "historic_dist": prop.get("historic_dist"), "landmark": prop.get("landmark"),
        "strategies": prop.get("strategies"), "deal_score": ds, "opportunity_score": opp,
        "owner": prop.get("owner"), "owner_type": prop.get("owner_type"),
        "last_sale_price": prop.get("last_sale_price"), "last_sale_date": prop.get("last_sale_date"),
        "active_mortgage_amt": prop.get("active_mortgage_amt"), "open_liens": prop.get("open_liens"),
        "distress_signal": prop.get("distress_signal"),
        "assess_land": prop.get("assess_land"), "assess_total": prop.get("assess_total"),
    }
    mc = prop.get("market_comps")
    if mc:
        ctx["market_comps"] = {
            "median_price_psf": mc.get("median_price_psf"),
            "count": mc.get("count"),
        }
    pipe = prop.get("pipeline")
    if pipe:
        ctx["pipeline"] = {"count": pipe.get("count"), "total_units": pipe.get("total_units")}
    uw = prop.get("underwriting")
    if uw:
        ctx["underwriting"] = {
            "scenario_label": uw.get("scenario_label"),
            "irr": uw.get("irr"), "equity_multiple": uw.get("equity_multiple"),
            "total_dev_cost": uw.get("total_dev_cost"),
            "equity_structure": uw.get("equity_structure"),
        }
    return json.dumps(ctx, default=str, indent=2)


_AGENT_SYSTEM_PROMPTS = {
    "property": (
        "You are a Property Research Agent for a NYC real estate development firm. "
        "Analyze ONLY the property data provided. Note ownership history, prior sale "
        "activity, and anything unusual about the record. If information is missing "
        "(e.g. no sale history found), say so plainly rather than guessing."
    ),
    "zoning": (
        "You are a Zoning Agent. Analyze the zoning district, FAR utilization, and any "
        "historic/landmark flags provided. Identify development constraints and note "
        "which conclusions require confirmation from NYC Planning or a zoning attorney. "
        "Never state a zoning conclusion as certain — always flag it as calculated/preliminary."
    ),
    "market": (
        "You are a Market Agent. Analyze the market comps and pipeline data provided to "
        "assess demand signals, price levels, and nearby competitive supply. If comps "
        "data is sparse or missing, say so explicitly instead of inventing numbers."
    ),
    "development": (
        "You are a Development Agent. Analyze development potential based on unused FAR, "
        "lot size, and classified strategy signals. Comment on plausible massing scale "
        "and site constraints. All massing conclusions are preliminary, not a zoning opinion."
    ),
    "financial": (
        "You are a Financial Agent. Review the deal score, opportunity score, assessed "
        "values, and any market pricing provided. Flag economic weaknesses or gaps in "
        "the underwriting inputs (e.g. no verified sale comps, no cost estimate)."
    ),
    "risk": (
        "You are a Risk Agent. Identify legal, regulatory, ownership, and execution risks "
        "from the data provided — historic designation, distress signals, liens, zoning "
        "constraints. Do not claim risks that aren't supported by the data; flag unknowns "
        "as unknowns rather than assuming the worst or the best case."
    ),
}


def run_agent(agent_key: str, prop: dict, api_key: str) -> dict:
    """Run a single named agent (see AGENT_ORDER, excluding 'investment_committee')."""
    system = _AGENT_SYSTEM_PROMPTS.get(agent_key)
    if not system:
        return {"error": f"Unknown agent: {agent_key}"}
    context = _property_context(prop)
    user_prompt = f"Property data:\n{context}\n\nProvide your findings for this property."
    return _call_agent(system, user_prompt, api_key, _FINDINGS_SCHEMA)


def run_investment_committee(prop: dict, agent_outputs: dict, api_key: str) -> dict:
    """
    Run the Investment Committee Agent — synthesizes all other agent outputs
    into a final GO/WATCH/REJECT recommendation with thesis, risks, unknowns,
    and next steps. Does not blindly accept prior agent claims: instructed to
    weigh confidence/verified flags.
    """
    system = (
        "You are the Investment Committee Agent for a NYC real estate development "
        "firm reviewing a preliminary screening report. You receive the property "
        "data and the findings of five specialist agents (property, zoning, market, "
        "development, financial, risk). Do NOT blindly accept their conclusions — "
        "weigh each finding's stated confidence and verified/estimated status. "
        "Produce a final investment thesis, key risks, key unknowns requiring "
        "diligence, and a prioritized list of next steps, plus a GO/WATCH/REJECT "
        "recommendation. This is a preliminary screening tool — reserve GO for "
        "genuinely strong, well-evidenced opportunities; use WATCH when promising "
        "but unconfirmed; use REJECT when the data shows clear disqualifying issues "
        "or persistently weak economics."
    )
    context = _property_context(prop)
    findings_str = json.dumps(agent_outputs, default=str, indent=2)
    user_prompt = (
        f"Property data:\n{context}\n\n"
        f"Specialist agent findings:\n{findings_str}\n\n"
        "Synthesize a final Investment Committee review."
    )
    return _call_agent(system, user_prompt, api_key, _IC_SCHEMA)


def run_all_agents(prop: dict, api_key: str, progress_callback=None) -> dict:
    """
    Run all specialist agents sequentially, then the Investment Committee
    synthesis agent. Returns:
        {
          "property": {...}, "zoning": {...}, "market": {...},
          "development": {...}, "financial": {...}, "risk": {...},
          "investment_committee": {...},
        }
    progress_callback(agent_key, i, n): optional, called after each agent.
    """
    specialist_keys = [k for k in AGENT_ORDER if k != "investment_committee"]
    outputs: dict = {}
    n = len(specialist_keys) + 1

    for i, key in enumerate(specialist_keys, start=1):
        outputs[key] = run_agent(key, prop, api_key)
        if progress_callback:
            progress_callback(key, i, n)

    outputs["investment_committee"] = run_investment_committee(prop, outputs, api_key)
    if progress_callback:
        progress_callback("investment_committee", n, n)

    return outputs
