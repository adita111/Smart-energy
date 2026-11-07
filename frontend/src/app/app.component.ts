
import { Component, OnInit, inject, OnDestroy, NgZone, PLATFORM_ID, } from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { interval, Subscription } from 'rxjs';

import {
  CampusService,
  Building,
  Floor,
  Room,
  SensorReading,
  ScheduledActivity,
  OptimizationResult,
  EnergyComparison,
  UlbsActivity,
  WeekParity
} from './services/campus.service';


@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit, OnDestroy {
  private campusService = inject(CampusService);
  private ngZone = inject(NgZone);
  private platformId = inject(PLATFORM_ID);
  private temperatureTimer?: Subscription;
  private temperatureRequestInProgress = false;

  ulbsRooms: string[] = [];
  ulbsActivities: UlbsActivity[] = [];
  selectedUlbsRoom = '';
  selectedUlbsWeekday = 0;
  selectedUlbsParity: WeekParity = 'all';
  ulbsLoading = false;
  ulbsError = '';

  showOptimizationResults = false;
  optimizationWeekday = 0;
  optimizationWeekParity: 'odd' | 'even' = 'odd';

  buildings: Building[] = [];
  floors: Floor[] = [];
  rooms: Room[] = [];

  selectedBuilding = '';
  selectedFloor: number | null = null;
  selectedRoom: Room | null = null;

  sensorReading: SensorReading | null = null;
  schedule: ScheduledActivity[] = [];

  loading = false;
  error = '';

  optimizationResult: OptimizationResult | null = null;
optimizing = false;
optimizationError = '';

energyResult: EnergyComparison | null = null;
energyLoading = false;
energyError = '';

outsideTemperature = -3;
simulationWeekday = 0;
selectedEnergyRoom = '';
energyWeekParity: 'odd' | 'even' = 'odd';

showEnergyHistory = false;

  
ngOnInit(): void {
  this.loadBuildings();
  this.loadUlbsRooms();

  // Run polling only in the browser
  if (isPlatformBrowser(this.platformId)) {

    // Keep the repeating timer outside Angular Zone
    this.ngZone.runOutsideAngular(() => {

      this.temperatureTimer = interval(10000).subscribe(() => {

        if (
          this.selectedRoom &&
          !this.temperatureRequestInProgress
        ) {

          // Re-enter Angular Zone for UI updates
          this.ngZone.run(() => {
            this.refreshTemperature();
          });

        }

      });

    });

  }
}


ngOnDestroy(): void {
  this.temperatureTimer?.unsubscribe();
}


  loadBuildings(): void {
    this.campusService.getBuildings().subscribe({
      next: (data) => {
        this.buildings = data;

        if (data.length > 0) {
          this.selectBuilding(data[0].id);
        }
      },
      error: () => {
        this.error = 'Could not load buildings';
      }
    });
  }

  selectBuilding(buildingId: string): void {
    this.selectedBuilding = buildingId;
    this.selectedFloor = null;
    this.selectedRoom = null;
    this.rooms = [];
    this.floors = [];

    this.campusService.getFloors(buildingId).subscribe({
      next: (data) => {
        this.floors = data;

        if (data.length > 0) {
          this.selectFloor(data[0].number);
        }
      },
      error: () => {
        this.error = 'Could not load floors';
      }
    });
  }

  selectFloor(floorNumber: number): void {
    this.selectedFloor = floorNumber;
    this.selectedRoom = null;
    this.sensorReading = null;
    this.schedule = [];

    this.campusService.getRooms(
      this.selectedBuilding,
      floorNumber
    ).subscribe({
      next: (data) => {
        this.rooms = data;

        if (data.length > 0) {
          this.selectRoom(data[0]);
        }
      },
      error: () => {
        this.error = 'Could not load rooms';
      }
    });
  }

selectRoom(room: Room): void {
  this.selectedRoom = room;
  this.selectedEnergyRoom = room.id;

  this.sensorReading = null;
  this.schedule = [];

  this.refreshRoom();
}


refreshRoom(): void {
  const room = this.selectedRoom;

  if (!room) {
    return;
  }

  this.error = '';

  // Check the temperature and update only if changed
  this.refreshTemperature();

  // Reload the room schedule
  this.campusService.getRoomSchedule(room.id).subscribe({
    next: (data) => {
      if (this.selectedRoom?.id === room.id) {
        this.schedule = data;
      }
    },
    error: () => {
      this.error = 'Could not load schedule';
    }
  });
}

  
runOptimization(): void {
  this.optimizing = true;
  this.optimizationError = '';
  this.optimizationResult = null;

  this.campusService.optimizeSchedule(
    this.optimizationWeekday,
    this.optimizationWeekParity
).subscribe({
    next: (result) => {
      this.optimizationResult = result;
      this.optimizing = false;

      console.log('Optimization result:', result);
    },
    error: (error) => {
      this.optimizing = false;

      this.optimizationError =
        error.error?.detail || 'Schedule optimization failed';

      console.error('Optimization error:', error);
    }
  });
  this.showOptimizationResults = true;
}



runEnergySimulation(): void {
  this.energyLoading = true;
  this.energyError = '';
  this.energyResult = null;
  this.showEnergyHistory = false;

  this.campusService.compareEnergy(
    this.outsideTemperature,
    this.simulationWeekday,
    this.energyWeekParity
  ).subscribe({
    next: (result) => {
      this.energyResult = result;
      this.energyLoading = false;

      // Select the first existing room if the current
      // selection is no longer valid.
      const roomExists = this.rooms.some(
        room => room.id === this.selectedEnergyRoom
      );

      if (!roomExists) {
        this.selectedEnergyRoom =
          this.rooms.length > 0
            ? this.rooms[0].id
            : '';
      }
    },
    error: (error) => {
      this.energyLoading = false;
      this.energyError =
        error.error?.detail || 'Energy simulation failed';
    }
  });
}

toggleEnergyHistory(): void {
  this.showEnergyHistory = !this.showEnergyHistory;
}

getHeatingBarWidth(value: number): number {
  if (!this.energyResult) {
    return 0;
  }

  const maxValue = Math.max(
    this.energyResult.baseline.heating_kwh_thermal,
    this.energyResult.smart_control.heating_kwh_thermal,
    this.energyResult.optimized_smart.heating_kwh_thermal,
    1
  );

  return value / maxValue * 100;
}

getRoomHistory() {
  if (!this.energyResult) {
    return [];
  }

  return this.energyResult.smart_control.history.filter(
    item =>
      item.room_id === this.selectedEnergyRoom
  );
}

getLeftRoomHistory() {
  return this.getRoomHistory().slice(0, 24);
}

getRightRoomHistory() {
  return this.getRoomHistory().slice(24, 48);
}

refreshTemperature(): void {
  const room = this.selectedRoom;

  if (!room || this.temperatureRequestInProgress) {
    return;
  }

  this.temperatureRequestInProgress = true;

  this.campusService.getRoomSensors(room.id).subscribe({
    next: (sensors) => {
      const tempSensor = sensors.find(
        sensor => sensor.sensor_type === 'temperature'
      );

      if (!tempSensor) {
        this.temperatureRequestInProgress = false;
        return;
      }

      this.campusService.getSensorReading(tempSensor.id).subscribe({
        next: (reading) => {
          if (this.selectedRoom?.id === room.id) {
            if (
              this.sensorReading === null ||
              this.sensorReading.value !== reading.value
            ) {
              this.sensorReading = reading;
            }
          }

          this.temperatureRequestInProgress = false;
        },
        error: (error) => {
          console.error('Temperature reading error:', error);
          this.temperatureRequestInProgress = false;
        }
      });
    },
    error: (error) => {
      console.error('Sensor loading error:', error);
      this.temperatureRequestInProgress = false;
    }
  });
}


loadUlbsRooms(): void {
  this.ulbsError = '';

  this.campusService.getUlbsRooms().subscribe({
    next: (rooms) => {
      this.ulbsRooms = rooms;

      if (rooms.length === 0) {
        this.selectedUlbsRoom = '';
        this.ulbsActivities = [];
        return;
      }

      if (!rooms.includes(this.selectedUlbsRoom)) {
        this.selectedUlbsRoom = rooms[0];
      }

      this.loadUlbsSchedule();
    },
    error: (error) => {
      console.error('ULBS rooms error:', error);
      this.ulbsError = 'Could not load ULBS rooms';
    }
  });
}

loadUlbsSchedule(): void {
  if (!this.selectedUlbsRoom) {
    this.ulbsActivities = [];
    return;
  }

  this.ulbsLoading = true;
  this.ulbsError = '';

  const roomId = this.selectedUlbsRoom;
  const weekday = this.selectedUlbsWeekday;
  const parity = this.selectedUlbsParity;

  this.campusService.getUlbsSchedule(
    roomId,
    weekday,
    parity
  ).subscribe({
    next: (activities) => {
      // Ignore responses from an old selection.
      if (
        this.selectedUlbsRoom !== roomId ||
        this.selectedUlbsWeekday !== weekday ||
        this.selectedUlbsParity !== parity
      ) {
        return;
      }

      this.ulbsActivities = activities;
      this.ulbsLoading = false;
    },
    error: (error) => {
      if (
        this.selectedUlbsRoom !== roomId ||
        this.selectedUlbsWeekday !== weekday ||
        this.selectedUlbsParity !== parity
      ) {
        return;
      }

      console.error('ULBS schedule error:', error);
      this.ulbsError = 'Could not load ULBS schedule';
      this.ulbsLoading = false;
    }
  });
}

toggleOptimization(): void {
  if (this.showOptimizationResults) {
    this.showOptimizationResults = false;
    return;
  }

  this.showOptimizationResults = true;

  if (!this.optimizationResult) {
    this.runOptimization();
  }
}


}
