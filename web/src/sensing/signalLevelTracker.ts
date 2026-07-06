import { percentile, rmsDb, updateNoiseFloor } from '../audio/dsp';
import type { ReceiverStatus, SignalLevelSnapshot } from '../types';

const MIC_CALIBRATION_MS = 1200;

export class SignalLevelTracker {
  private calibrationUntil = 0;
  private calibrationLevels: number[] = [];
  private levelDb = -120;
  private noiseFloorDb = -68;
  private status: ReceiverStatus = 'idle';

  startCalibration(nowMs: number): void {
    this.calibrationUntil = nowMs + MIC_CALIBRATION_MS;
    this.calibrationLevels = [];
    this.levelDb = -120;
    this.noiseFloorDb = -68;
    this.status = 'calibrating';
  }

  stop(): void {
    this.status = 'idle';
    this.calibrationUntil = 0;
    this.calibrationLevels = [];
  }

  process(input: Float32Array, nowMs: number): SignalLevelSnapshot {
    const currentLevel = rmsDb(input);
    this.levelDb = this.levelDb * 0.76 + currentLevel * 0.24;

    if (this.calibrationUntil > 0) {
      if (nowMs < this.calibrationUntil) {
        this.calibrationLevels.push(currentLevel);
        this.status = 'calibrating';
        return this.snapshot();
      }
      const floor = percentile(this.calibrationLevels, 0.35);
      if (floor !== null) this.noiseFloorDb = floor;
      this.calibrationUntil = 0;
      this.calibrationLevels = [];
    }

    this.noiseFloorDb = updateNoiseFloor(this.noiseFloorDb, currentLevel);
    this.status = 'listening';
    return this.snapshot();
  }

  snapshot(): SignalLevelSnapshot {
    return {
      status: this.status,
      levelDb: this.levelDb,
      noiseFloorDb: this.noiseFloorDb
    };
  }
}
