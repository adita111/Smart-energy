"""Non-destructive timetable proposal engine (CP-SAT).

Uses estimated campus metadata in DEMO mode; never writes ULBS schedule.
Call with a single weekday and week parity for bounded execution.
"""
from collections import defaultdict
from datetime import time

from ortools.sat.python import cp_model

from services.room_service import get_all_rooms
from services.schedule_service import get_all_activities

STEP = 15


def _minute(value):
    parsed = time.fromisoformat(value)
    return parsed.hour * 60 + parsed.minute


def _slots(activity):
    start, end = _minute(activity.start_time), _minute(activity.end_time)
    return range(start // STEP, (end - 1) // STEP + 1) if end > start else range(0)


def _building(room):
    # Prefer explicit building_id; fallback for generated IDs IE101, IM202...
    return getattr(room, "building_id", None) or "".join(c for c in room.id if c.isalpha())


def _snapshot(activities, rooms, status, message, **extra):
    by_id = {r.id: r for r in rooms}
    zones = {by_id[a.room_id].heating_zone for a in activities if a.room_id in by_id}
    return {
        "status": status,
        "message": message,
        "original_zone_count": len(zones),
        "optimized_zone_count": len(zones),
        "moved_activities": 0,
        "activities": [
            {
                **a.model_dump(),
                "original_room_id": a.room_id,
                "heating_zone": getattr(by_id.get(a.room_id), "heating_zone", None),
                "moved": False,
            }
            for a in activities
        ],
        "estimated_constraints": True,
        **extra,
    }


def optimize_schedule(activities=None, weekday=0, week_parity="odd", demo_mode=True):
    """Propose alternative rooms, not edits to the official timetable.

    Optimizes *active heating-zone 15-minute slots*, then number of room moves.
    With unknown student counts, candidates must have capacity >= ORIGINAL
    estimated room capacity, a conservative proxy, not a real safety guarantee.
    """
    if week_parity not in {"odd", "even"}:
        raise ValueError("week_parity must be 'odd' or 'even'")
    if not 0 <= weekday <= 6:
        raise ValueError("weekday must be between 0 and 6")

    if activities is None:
        activities = get_all_activities(weekday=weekday, week_parity=week_parity)
    else:
        activities = [a for a in activities if a.weekday == weekday]

    rooms = [r for r in get_all_rooms() if r.room_type != "hallway"]
    by_id = {r.id: r for r in rooms}
    result_meta = {"weekday": weekday, "week_parity": week_parity}
    if not activities:
        return _snapshot([], rooms, "success", "No activities for selected day.", **result_meta)
    if not demo_mode:
        return _snapshot(activities, rooms, "skipped_unverified_capacity",
                         "Verified enrollment/capacity unavailable; official allocations kept.", **result_meta)

    # Keep backend responsive even for a campus-wide timetable.
    if len(activities) > 350:
        return _snapshot(activities, rooms, "too_many_activities",
                         "More than 350 activities for this day; narrow the scope before solving.", **result_meta)

    # Real imported data can contain simultaneous records for shared lectures
    # in the SAME room. Keep such activities fixed, to avoid fake conflicts.
    initially_booked = defaultdict(list)
    for idx, a in enumerate(activities):
        for slot in _slots(a):
            initially_booked[(a.room_id, slot)].append(idx)
    locked = set()
    for ids in initially_booked.values():
        if len(ids) > 1:
            locked.update(ids)

    candidates = {}
    for idx, a in enumerate(activities):
        original = by_id.get(a.room_id)
        if original is None:
            candidates[idx] = []
            continue
        if idx in locked:
            candidates[idx] = [original]
            continue
        similar = []
        for r in rooms:
            if _building(r) != _building(original):
                continue
            if r.room_type == "hallway":
                continue
            # Capacity values are synthetic: proxy prevents reducing *estimated*
            # room capacity, but does not prove real classroom feasibility.
            if r.capacity < original.capacity:
                continue
            if a.activity_type == "laboratory" and r.room_type not in ("lab", "laboratory"):
                continue
            if a.required_equipment and not set(a.required_equipment).issubset(set(r.equipment)):
                continue
            similar.append(r)
        similar.sort(key=lambda r: (
            r.id != original.id,
            r.heating_zone != original.heating_zone,
            abs(r.area_m2 - original.area_m2),
            r.id,
        ))
        # Include original, limit search to a few rooms, favor energy grouping.
        candidates[idx] = similar[:6] or [original]
        if original.id not in {r.id for r in candidates[idx]}:
            candidates[idx] = [original] + candidates[idx][:5]

    model = cp_model.CpModel()
    assignment = {}
    room_slot_vars = defaultdict(list)
    zone_slot_vars = defaultdict(list)
    for idx, a in enumerate(activities):
        choices = candidates[idx]
        if not choices:
            continue
        vars_for_a = []
        for r in choices:
            v = model.NewBoolVar(f"a{idx}_r{r.id}")
            assignment[(idx, r.id)] = v
            vars_for_a.append(v)
            for slot in _slots(a):
                room_slot_vars[(r.id, slot)].append((idx, v))
                zone_slot_vars[(r.heating_zone, slot)].append(v)
        model.AddExactlyOne(vars_for_a)

    # An existing shared lecture may have multiple timetable records in a
    # single room/slot. Treat the already-locked records as one fixed booking.
    for (room_id, slot), members in room_slot_vars.items():
        unique_vars = []
        locked_members = [(idx, v) for idx, v in members if idx in locked]
        if locked_members:
            for idx, v in members:
                if idx not in locked:
                    model.Add(v == 0)
        else:
            unique_vars = [v for _, v in members]
            model.AddAtMostOne(unique_vars)

    # Unknown rooms remain untouched, and reserve their original room slots.
    missing = [i for i, a in enumerate(activities) if not candidates[i]]
    for idx in missing:
        a = activities[idx]
        for slot in _slots(a):
            for other_idx, v in room_slot_vars.get((a.room_id, slot), []):
                model.Add(v == 0)

    active_zone_vars = []
    for key, variables in zone_slot_vars.items():
        v = model.NewBoolVar(f"active_{key[0]}_{key[1]}")
        for a_var in variables:
            model.Add(a_var <= v)
        active_zone_vars.append(v)

    moved_vars = [v for (idx, room_id), v in assignment.items()
                  if room_id != activities[idx].room_id]
    # A zone-slot costs much more than a single move; both terms are proxies.
    model.Minimize(100 * sum(active_zone_vars) + sum(moved_vars))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 7
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _snapshot(activities, rooms, "no_feasible_solution",
                         "Solver could not find a valid proposal; official allocations kept.", **result_meta)

    proposed = []
    moved_count = 0
    optimized_zones = set()
    original_zones = {by_id[a.room_id].heating_zone for a in activities if a.room_id in by_id}
    for idx, a in enumerate(activities):
        selected = next((r for r in candidates[idx]
                         if solver.Value(assignment[(idx, r.id)]) == 1), None)
        new_room = selected or by_id.get(a.room_id)
        new_id = new_room.id if new_room else a.room_id
        moved = new_id != a.room_id
        moved_count += int(moved)
        if new_room:
            optimized_zones.add(new_room.heating_zone)
        proposed.append({
            **a.model_dump(),
            "original_room_id": a.room_id,
            "room_id": new_id,
            "heating_zone": getattr(new_room, "heating_zone", None),
            "moved": moved,
        })

    return {
        "status": "optimal" if status == cp_model.OPTIMAL else "feasible",
        "message": "DEMO proposal only: room capacities and enrollments are unverified; no ULBS data changed.",
        "original_zone_count": len(original_zones),
        "optimized_zone_count": len(optimized_zones),
        "moved_activities": moved_count,
        "activities": proposed,
        "estimated_constraints": True,
        "objective": "minimize occupied heating-zone 15-minute intervals and room changes",
        **result_meta,
    }
