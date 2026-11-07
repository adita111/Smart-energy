
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs/internal/Observable';

export interface Building {
  id: string;
  name: string;
  address: string | null;
}

export interface Floor {
  id: string;
  building_id: string;
  number: number;
  name: string | null;
}

export interface Room {
  id: string;
  building: string;
  floor: number;
  area_m2: number;
  capacity: number;
  room_type: string;
  heating_zone: string;
}

export interface Sensor {
  id: string;
  room_id: string;
  sensor_type: string;
  unit: string;
  simulated: boolean;
}

export interface SensorReading {
  sensor_id: string;
  room_id: string;
  value: number;
  unit: string;
  simulated: boolean;
}

export interface ScheduledActivity {
  id: string;
  room_id: string;
  course_name: string;
  weekday: number;
  start_time: string;
  end_time: string;
  group: string;
  students_count: number;
  activity_type: string;
}


export interface OptimizedActivity extends ScheduledActivity {
  original_room_id: string;
  heating_zone: string;
  moved: boolean;
}

export interface OptimizationResult {
  status: string;
  original_zone_count: number;
  optimized_zone_count: number;
  moved_activities: number;
  activities: OptimizedActivity[];
  message?: string;
}


export interface EnergyHistory {
  time: string;
  room_id: string;
  heating_zone: string;
  temperature: number;
  heating_on: boolean;
  lights_on: boolean;
  occupied: boolean;
}

export interface EnergyScenario {
  scenario: string;
  heating_kwh_thermal: number;
  lighting_kwh_electric: number;
  discomfort_minutes: number;
  occupied_room_minutes: number;
  comfort_percentage: number;
  history: EnergyHistory[];
}

export interface EnergyComparison {
  outside_temperature: number;
  weekday: number;
  baseline: EnergyScenario;
  smart_control: EnergyScenario;
  optimized_smart: EnergyScenario;
  heating_savings_percent: number;
  schedule_optimization: {
    moved_activities: number;
    original_zone_count: number;
    optimized_zone_count: number;
  };
  ai_insights?: Array<{
    type: string;
    title: string;
    description: string;
  }>;
}


export interface UlbsActivity {
  id: string;
  room_id: string;
  course_name: string;
  weekday: number;
  start_time: string;
  end_time: string;
  group: string;
  students_count: number | null;
  activity_type: string;
  required_equipment: string[];
  professor: string | null;
  is_odd_week: boolean;
  is_even_week: boolean;
  source: string;
  source_schedule_id: number;
  source_slot_id: number;
  source_room_id: string | null;
  formation_ids: number[];
  formation_names: string[];
  requested_formation_ids: number[];
}

export type WeekParity = 'all' | 'odd' | 'even';


@Injectable({
  providedIn: 'root'
})
export class CampusService {
  private http = inject(HttpClient);
  private apiUrl = 'http://127.0.0.1:8000';

  getBuildings() {
    return this.http.get<Building[]>(
      `${this.apiUrl}/buildings`
    );
  }

  getFloors(buildingId: string) {
    return this.http.get<Floor[]>(
      `${this.apiUrl}/buildings/${buildingId}/floors`
    );
  }

  getRooms(buildingId: string, floor: number) {
    return this.http.get<Room[]>(
      `${this.apiUrl}/buildings/${buildingId}/floors/${floor}/rooms`
    );
  }

  getRoomSensors(roomId: string) {
    return this.http.get<Sensor[]>(
      `${this.apiUrl}/rooms/${roomId}/sensors`
    );
  }

  getSensorReading(sensorId: string) {
    return this.http.get<SensorReading>(
      `${this.apiUrl}/sensors/${sensorId}/reading`
    );
  }

  getRoomSchedule(roomId: string) {
    return this.http.get<ScheduledActivity[]>(
      `${this.apiUrl}/rooms/${roomId}/schedule`
    );
  }
  optimizeSchedule(
  weekday: number,
  weekParity: 'odd' | 'even'
): Observable<OptimizationResult> {
  return this.http.get<OptimizationResult>(
    `${this.apiUrl}/optimize/schedule`,
    {
      params: {
        weekday: String(weekday),
        week_parity: weekParity
      }
    }
  );
}
compareEnergy(
  outsideTemperature: number,
  weekday: number,
  weekParity: 'odd' | 'even' = 'odd'
) {
  return this.http.get<EnergyComparison>(
    `${this.apiUrl}/simulation/compare`,
    {
      params: {
        outside_temperature: outsideTemperature,
        weekday: weekday,
        week_parity: weekParity
      }
    }
  );
}


getUlbsRooms() {
  return this.http.get<string[]>(
    `${this.apiUrl}/ulbs/rooms`
  );
}

getUlbsSchedule(
  roomId: string,
  weekday?: number,
  weekParity: WeekParity = 'all'
) {
  const params: Record<string, string> = {
    room_id: roomId,
    week_parity: weekParity
  };

  if (weekday !== undefined) {
    params['weekday'] = String(weekday);
  }

  return this.http.get<UlbsActivity[]>(
    `${this.apiUrl}/ulbs/schedule`,
    { params }
  );
}

}
