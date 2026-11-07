
from datetime import time

from services.room_service import get_all_rooms, get_all_states
from services.schedule_service import get_all_activities
from services.campus_service import get_heating_zones
from services.schedule_optimizer import optimize_schedule
from services.energy_insights import generate_energy_insights
from services.thermal_service import calculate_next_temperature

STEP_MINUTES = 30
COMFORT_TEMP = 21.0
ECO_TEMP = 16.0
LIGHTING_W_PER_M2 = 10.0


def to_minutes(value):
    parsed = time.fromisoformat(value)
    return parsed.hour * 60 + parsed.minute


def activity_value(activity, field):
    if isinstance(activity, dict):
        return activity[field]

    return getattr(activity, field)


def room_occupied(room_id, minute, activities_by_room, weekday):
    return any(
        activity_value(a, "weekday") == weekday
        and to_minutes(activity_value(a, "start_time")) <= minute
        < to_minutes(activity_value(a, "end_time"))
        for a in activities_by_room.get(room_id, [])
    )


def predict_temperature(
    room,
    current_temperature,
    outside_temperature,
    minutes,
    heating_on
):
    if minutes <= 0:
        return current_temperature

    return calculate_next_temperature(
        current_temp=current_temperature,
        outside_temp=outside_temperature,
        heating_on=heating_on,
        heating_power=room.heating_power,
        heat_loss_coefficient=room.heat_loss_coefficient,
        thermal_capacity=room.thermal_capacity,
        minutes=minutes
    )


def should_preheat_zone(
    zone_rooms,
    temperatures,
    activities_by_room,
    minute,
    weekday,
    outside_temperature
):
    comfort_limit = COMFORT_TEMP - 0.5

    for room in zone_rooms:
        for activity in activities_by_room.get(room.id, []):

            if activity_value(activity, "weekday") != weekday:
                continue

            course_start = to_minutes(
                activity_value(activity, "start_time")
            )

            if course_start <= minute:
                continue

            time_until_course = course_start - minute

            # Check if heating continuously from now
            # can reach the comfort temperature.
            temp_if_on_now = predict_temperature(
                room=room,
                current_temperature=temperatures[room.id],
                outside_temperature=outside_temperature,
                minutes=time_until_course,
                heating_on=True
            )

            # If heating is insufficient, start immediately.
            if temp_if_on_now < comfort_limit:
                return True

            # Predict cooling if heating is delayed.
            temperature_after_wait = predict_temperature(
                room=room,
                current_temperature=temperatures[room.id],
                outside_temperature=outside_temperature,
                minutes=STEP_MINUTES,
                heating_on=False
            )

            remaining_minutes = max(
                0,
                time_until_course - STEP_MINUTES
            )

            predicted_temperature = predict_temperature(
                room=room,
                current_temperature=temperature_after_wait,
                outside_temperature=outside_temperature,
                minutes=remaining_minutes,
                heating_on=True
            )

            if predicted_temperature < comfort_limit:
                return True

    return False


def simulate_scenario(
    scenario_name,
    activities,
    outside_temperature,
    weekday,
    smart_control
):
    rooms = get_all_rooms()
    states = get_all_states()
    zones = get_heating_zones()

    # Independent copy of initial room temperatures.
    temperatures = {
        state.room_id: state.current_temperature
        for state in states
    }

    room_map = {
        room.id: room
        for room in rooms
        if room.id in temperatures
    }

    # Index once: large real ULBS timetables must not be scanned for every room.
    activities_by_room = {}
    for activity in activities:
        room_id = activity_value(activity, "room_id")
        activities_by_room.setdefault(room_id, []).append(activity)

    heating_energy = 0.0
    lighting_energy = 0.0
    discomfort_minutes = 0
    occupied_room_minutes = 0
    history = []

    # Each heating zone has its own control state.
    zone_states = {
        zone.id: False
        for zone in zones
    }

    for minute in range(0, 1440, STEP_MINUTES):
        current_time = (
            f"{minute // 60:02d}:"
            f"{minute % 60:02d}"
        )

        for zone in zones:
            zone_rooms = [
                room_map[room_id]
                for room_id in zone.room_ids
                if room_id in room_map
            ]

            if not zone_rooms:
                continue

            if smart_control:
                occupied_rooms = [
                    room for room in zone_rooms
                    if room_occupied(
                        room.id,
                        minute,
                        activities_by_room,
                        weekday
                    )
                ]

                preheat_required = should_preheat_zone(
                    zone_rooms=zone_rooms,
                    temperatures=temperatures,
                    activities_by_room=activities_by_room,
                    minute=minute,
                    weekday=weekday,
                    outside_temperature=outside_temperature
                )

                if occupied_rooms:
                    lowest_temp = min(
                        temperatures[room.id]
                        for room in occupied_rooms
                    )

                    # Predict whether the occupied rooms
                    # would become too cold in 15 minutes.
                    predicted_temps = [
                        predict_temperature(
                            room=room,
                            current_temperature=temperatures[room.id],
                            outside_temperature=outside_temperature,
                            minutes=STEP_MINUTES,
                            heating_on=False
                        )
                        for room in occupied_rooms
                    ]

                    if min(predicted_temps) < COMFORT_TEMP - 0.5:
                        zone_states[zone.id] = True

                    elif lowest_temp >= COMFORT_TEMP + 0.5:
                        zone_states[zone.id] = False

                    if preheat_required:
                        zone_states[zone.id] = True

                elif preheat_required:
                    # Start heating before an upcoming course.
                    zone_states[zone.id] = True

                else:
                    # Eco mode when the zone has no
                    # ongoing or upcoming heating need.
                    lowest_temp = min(
                        temperatures[room.id]
                        for room in zone_rooms
                    )

                    if lowest_temp < ECO_TEMP - 0.5:
                        zone_states[zone.id] = True

                    elif lowest_temp >= ECO_TEMP + 0.5:
                        zone_states[zone.id] = False

                heating_on = zone_states[zone.id]

            else:
                # Baseline: heating from 06:00 to 18:00.
                heating_on = 360 <= minute < 1080

            # Update each room in the heating zone.
            for room in zone_rooms:
                old_temp = temperatures[room.id]

                occupied = room_occupied(
                    room.id,
                    minute,
                    activities_by_room,
                    weekday
                )

                # Measure thermal comfort at the beginning
                # of each occupied interval.
                if occupied:
                    occupied_room_minutes += STEP_MINUTES

                    if old_temp < COMFORT_TEMP - 0.5:
                        discomfort_minutes += STEP_MINUTES

                next_temp = calculate_next_temperature(
                    current_temp=old_temp,
                    outside_temp=outside_temperature,
                    heating_on=heating_on,
                    heating_power=room.heating_power,
                    heat_loss_coefficient=room.heat_loss_coefficient,
                    thermal_capacity=room.thermal_capacity,
                    minutes=STEP_MINUTES
                )

                temperatures[room.id] = next_temp

                # Thermal energy consumption.
                if heating_on:
                    heating_energy += (
                        room.heating_power / 1000
                        * STEP_MINUTES / 60
                    )

                # Smart lighting: ON only during courses.
                # Baseline lighting: ON from 06:00 to 18:00.
                if smart_control:
                    lights_on = occupied
                else:
                    lights_on = 360 <= minute < 1080

                if lights_on:
                    lighting_energy += (
                        room.area_m2
                        * LIGHTING_W_PER_M2
                        / 1000
                        * STEP_MINUTES / 60
                    )

                history.append({
                    "time": current_time,
                    "room_id": room.id,
                    "heating_zone": zone.id,
                    "temperature": next_temp,
                    "heating_on": heating_on,
                    "lights_on": lights_on,
                    "occupied": occupied
                })

    comfort_percentage = (
        100 * (
            1 - discomfort_minutes / occupied_room_minutes
        )
        if occupied_room_minutes > 0
        else 100.0
    )

    return {
        "scenario": scenario_name,
        "heating_kwh_thermal": round(heating_energy, 2),
        "lighting_kwh_electric": round(lighting_energy, 2),
        "discomfort_minutes": discomfort_minutes,
        "occupied_room_minutes": occupied_room_minutes,
        "comfort_percentage": round(comfort_percentage, 2),
        "history": history
    }


def compare_energy(outside_temperature=-3.0, weekday=0, week_parity="odd", optimization_mode="demo"):
    if week_parity not in {"odd", "even"}:
        raise ValueError("week_parity must be 'odd' or 'even'")

    original_activities = get_all_activities(
        weekday=weekday, week_parity=week_parity
    )
    if optimization_mode not in {"demo", "safe"}:
        raise ValueError("optimization_mode must be 'demo' or 'safe'")
    optimized = optimize_schedule(
        activities=original_activities,
        weekday=weekday,
        week_parity=week_parity,
        demo_mode=(optimization_mode == "demo"),
    )
    optimized_activities = optimized["activities"]

    # Scenario A: original schedule + fixed heating.
    baseline = simulate_scenario(
        scenario_name="baseline",
        activities=original_activities,
        outside_temperature=outside_temperature,
        weekday=weekday,
        smart_control=False
    )

    # Scenario B: original schedule + predictive heating.
    smart = simulate_scenario(
        scenario_name="smart_control",
        activities=original_activities,
        outside_temperature=outside_temperature,
        weekday=weekday,
        smart_control=True
    )

    # Scenario C: optimized schedule + predictive heating.
    optimized_smart = simulate_scenario(
        scenario_name="optimized_smart",
        activities=optimized_activities,
        outside_temperature=outside_temperature,
        weekday=weekday,
        smart_control=True
    )

    baseline_heating = baseline["heating_kwh_thermal"]

    heating_savings_percent = (
        100 * (
            baseline_heating
            - optimized_smart["heating_kwh_thermal"]
        ) / baseline_heating
        if baseline_heating > 0
        else 0
    )

    return {
        "outside_temperature": outside_temperature,
        "weekday": weekday,
        "week_parity": week_parity,
        "schedule_source": "ulbs",
        "optimization_mode": optimization_mode,
        "ai_insights": generate_energy_insights(baseline, smart, optimized_smart, optimized),
        "baseline": baseline,
        "smart_control": smart,
        "optimized_smart": optimized_smart,
        "heating_savings_percent": round(
            heating_savings_percent, 2
        ),
        "schedule_optimization": {
            "status": optimized["status"],
            "estimated_constraints": optimized.get("estimated_constraints", True),
            "message": optimized.get("message", ""),
            "moved_activities": optimized["moved_activities"],
            "original_zone_count": optimized["original_zone_count"],
            "optimized_zone_count": optimized["optimized_zone_count"]
        }
    }
