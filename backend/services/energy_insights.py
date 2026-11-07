"""Explain deterministic simulation outcomes; no external LLM or fabricated savings."""


def generate_energy_insights(baseline, smart, optimized, optimization):
    base_h = baseline["heating_kwh_thermal"]
    smart_h = smart["heating_kwh_thermal"]
    optim_h = optimized["heating_kwh_thermal"]
    base_l = baseline["lighting_kwh_electric"]
    smart_l = smart["lighting_kwh_electric"]
    optim_l = optimized["lighting_kwh_electric"]
    messages = []

    delta = base_h - smart_h
    pct = (delta / base_h * 100) if base_h else 0
    messages.append({
        "type": "heating",
        "title": "Predictive heating vs fixed schedule",
        "description": (
            f"Simulated heating {'saving' if delta >= 0 else 'increase'}: "
            f"{abs(delta):.2f} kWh thermal ({abs(pct):.1f}%)."
        ),
    })

    lights_delta = base_l - smart_l
    messages.append({
        "type": "lighting",
        "title": "Occupancy-aware lighting",
        "description": (
            f"Compared with fixed-hours lighting, estimated reduction is "
            f"{lights_delta:.2f} kWh electric."
            if lights_delta >= 0 else
            f"Occupancy-aware lighting uses {-lights_delta:.2f} kWh electric more in this scenario."
        ),
    })

    comfort = smart["comfort_percentage"]
    if comfort < 95:
        messages.append({
            "type": "comfort_warning",
            "title": "Thermal comfort needs attention",
            "description": (
                f"Smart scenario meets the simulated comfort threshold for "
                f"{comfort:.1f}% of occupied room-time; review preheating."
            ),
        })

    if optimization.get("moved_activities", 0) > 0:
        messages.append({
            "type": "proposal",
            "title": "Room reallocation proposal",
            "description": (
                f"CP-SAT proposes {optimization['moved_activities']} room changes. "
                f"Estimated heating difference vs Smart Control: "
                f"{smart_h - optim_h:+.2f} kWh thermal; "
                f"lighting difference: {smart_l - optim_l:+.2f} kWh electric. "
                "This is a demo proposal, not a verified or applied ULBS timetable."
            ),
        })
    else:
        messages.append({
            "type": "proposal",
            "title": "No room changes applied",
            "description": optimization.get("message", "Original ULBS room allocations kept."),
        })

    return messages
