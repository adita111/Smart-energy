
from fastapi import FastAPI, HTTPException, Query

from models.room import Room
from models.building import Building, Floor
from models.heating_zone import HeatingZone
from models.room_state import RoomState, SimulationRequest
from fastapi.middleware.cors import CORSMiddleware
from services.schedule_optimizer import optimize_schedule
from services.energy_simulation_service import simulate_energy
from services.smart_energy_service import simulate_smart_energy
from services.energy_comparison_service import compare_energy

import httpx
from services.weather_service import get_weather_forecast

from datetime import datetime
from services.heating_controller import predict_heating_start

from models.sensor import Sensor, SensorReading

from services.sensor_service import (
    get_all_sensors,
    get_sensor_by_id,
    get_sensors_by_room,
    get_sensor_reading
)

from services.room_service import (
    get_all_rooms,
    get_room_by_id,
    get_room_state,
    update_room_state
)
from services.campus_service import (
    get_buildings,
    get_floors,
    get_heating_zones,
    get_rooms_on_floor
)

from models.scheduled_activity import ScheduledActivity
from services.schedule_service import (
    get_all_activities,
    get_room_schedule
)

from services.ulbs_schedule_service import (
    get_ulbs_rooms,
    get_ulbs_schedule
)

from services.ulbs_occupancy_service import (
    get_room_coverage,
    get_room_occupancy
)

from services.thermal_service import calculate_next_temperature


app = FastAPI(
    title="CampusMind AI",
    description="AI-powered energy optimization system",
    version="0.2.0"
)


@app.get("/")
def home():
    return {"message": "Welcome to CampusMind AI!"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/rooms", response_model=list[Room])
def get_rooms():
    return get_all_rooms()


@app.get("/rooms/{room_id}", response_model=Room)
def get_room(room_id: str):
    room = get_room_by_id(room_id)

    if room is None:
        raise HTTPException(404, "Room not found")

    return room


@app.get("/rooms/{room_id}/state", response_model=RoomState)
def get_state(room_id: str):
    state = get_room_state(room_id)

    if state is None:
        raise HTTPException(404, "Room state not found")

    return state


@app.post("/rooms/{room_id}/simulate", response_model=RoomState)
def simulate_room(room_id: str, request: SimulationRequest):
    room = get_room_by_id(room_id)
    state = get_room_state(room_id)

    if room is None or state is None:
        raise HTTPException(404, "Room not found")

    new_temperature = calculate_next_temperature(
        current_temp=state.current_temperature,
        outside_temp=request.outside_temperature,
        heating_on=request.heating_on,
        heating_power=room.heating_power,
        heat_loss_coefficient=room.heat_loss_coefficient,
        thermal_capacity=room.thermal_capacity,
        minutes=request.minutes
    )

    state.current_temperature = new_temperature
    state.heating_on = request.heating_on

    if request.heating_on:
        state.energy_consumed_kwh += (
            room.heating_power / 1000
        ) * (request.minutes / 60)

    update_room_state(state)

    return state


@app.get("/schedule", response_model=list[ScheduledActivity])
def get_schedule():
    return get_all_activities()


@app.get(
    "/rooms/{room_id}/schedule",
    response_model=list[ScheduledActivity]
)
def get_schedule_for_room(room_id: str):

    room = get_room_by_id(room_id)

    if room is None:
        raise HTTPException(
            status_code=404,
            detail="Room not found"
        )

    return get_room_schedule(room_id)


@app.get("/weather/forecast")
def weather_forecast():
    try:
        forecast = get_weather_forecast()

        return {
            "city": "Sibiu",
            "forecast": forecast
        }

    except (httpx.HTTPError, KeyError, ValueError) as error:
        raise HTTPException(
            status_code=502,
            detail="Weather service unavailable"
        ) from error


@app.get("/rooms/{room_id}/heating/predict")
def predict_room_heating(
    room_id: str,
    course_start: datetime,
    outside_temperature: float = -3.0
):
    room = get_room_by_id(room_id)
    state = get_room_state(room_id)

    if room is None or state is None:
        raise HTTPException(
            status_code=404,
            detail="Room not found"
        )

    result = predict_heating_start(
        room=room,
        current_temperature=state.current_temperature,
        outside_temperature=outside_temperature,
        course_start=course_start,
        target_temperature=state.target_temperature
    )

    return result


@app.get("/buildings", response_model=list[Building])
def list_buildings():
    return get_buildings()


@app.get("/buildings/{building_id}/floors", response_model=list[Floor])
def list_floors(building_id: str):
    if not any(b.id == building_id for b in get_buildings()):
        raise HTTPException(404, "Building not found")

    return get_floors(building_id)


@app.get("/buildings/{building_id}/floors/{floor_number}/rooms",
         response_model=list[Room])
def list_rooms_on_floor(building_id: str, floor_number: int):
    floors = get_floors(building_id)

    if not any(f.number == floor_number for f in floors):
        raise HTTPException(404, "Floor not found")

    return get_rooms_on_floor(building_id, floor_number)


@app.get("/heating-zones", response_model=list[HeatingZone])
def list_heating_zones():
    return get_heating_zones()


@app.get("/sensors", response_model=list[Sensor])
def list_sensors():
    return get_all_sensors()


@app.get("/sensors/{sensor_id}", response_model=Sensor)
def sensor_details(sensor_id: str):
    sensor = get_sensor_by_id(sensor_id)

    if sensor is None:
        raise HTTPException(
            status_code=404,
            detail="Sensor not found"
        )

    return sensor


@app.get(
    "/sensors/{sensor_id}/reading",
    response_model=SensorReading
)
def sensor_reading(sensor_id: str):
    reading = get_sensor_reading(sensor_id)

    if reading is None:
        raise HTTPException(
            status_code=404,
            detail="Sensor reading not found"
        )

    return reading


@app.get("/rooms/{room_id}/sensors", response_model=list[Sensor])
def room_sensors(room_id: str):
    room = get_room_by_id(room_id)

    if room is None:
        raise HTTPException(
            status_code=404,
            detail="Room not found"
        )

    return get_sensors_by_room(room_id)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200"
    ],
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/optimize/schedule")  
def optimize_schedule_endpoint(
    weekday: int = 0,
    week_parity: str = "odd",
):
    if weekday < 0 or weekday > 6 or week_parity not in ("odd", "even"):
        raise HTTPException(status_code=422, detail="Invalid day or week parity")
    try:
        return optimize_schedule(
            weekday=weekday,
            week_parity=week_parity,
            demo_mode=True
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.get("/simulation/baseline")
def run_baseline_simulation(
    outside_temperature: float = -3.0
):
    return simulate_energy(
        outside_temperature=outside_temperature
    )


@app.get("/simulation/smart")
def run_smart_simulation(
    outside_temperature: float = -3.0,
    weekday: int = 0
):
    if weekday < 0 or weekday > 6:
        raise HTTPException(
            status_code=422,
            detail="Weekday must be between 0 and 6"
        )

    return simulate_smart_energy(
        outside_temperature=outside_temperature,
        weekday=weekday
    )



@app.get("/simulation/compare")
def compare_energy_scenarios(
    outside_temperature: float = -3.0,
    weekday: int = 0,
    week_parity: str = "odd",
    optimization_mode: str = "demo",
):
    if weekday < 0 or weekday > 6 or week_parity not in ("odd", "even"):
        raise HTTPException(
            status_code=422,
            detail="Invalid day or week parity"
        )

    try:
        return compare_energy(
            outside_temperature=outside_temperature,
            weekday=weekday,
            week_parity=week_parity,
            optimization_mode=optimization_mode,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        )



@app.get("/ulbs/rooms")
def list_ulbs_rooms():
    try:
        return get_ulbs_rooms()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc)
        ) from exc


@app.get("/ulbs/schedule")
def list_ulbs_schedule(
    room_id: str | None = None,
    weekday: int | None = Query(
        default=None, ge=0, le=6
    ),
    week_parity: str = Query(
        default="all",
        pattern="^(all|odd|even)$"
    )
):
    try:
        return get_ulbs_schedule(
            room_id=room_id,
            weekday=weekday,
            week_parity=week_parity
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc)
        ) from exc

@app.get("/ulbs/coverage")
def ulbs_room_coverage():
    try:
        return get_room_coverage()
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc)
        ) from exc


@app.get("/ulbs/occupancy")
def ulbs_room_occupancy(
    weekday: int = Query(ge=0, le=6),
    time: str = Query(
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    ),
    week_parity: str = Query(
        default="odd",
        pattern="^(odd|even)$"
    ),
    only_known_rooms: bool = False,
):
    try:
        return get_room_occupancy(
            weekday=weekday,
            time=time,
            week_parity=week_parity,
            only_known_rooms=only_known_rooms
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc)
        ) from exc

    