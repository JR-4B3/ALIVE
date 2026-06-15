import { goertzel, percentile, rmsDb, updateNoiseFloor } from '../audio/dsp';
import { EMITTERS, ZONES, ZONE_THRESHOLDS } from '../emitters';
import type { EmitterEstimate, EmitterFingerprint, ReceiverStatus, Zone, ZoneSnapshot } from '../types';
import { clamp, combineConfidence } from './sensorFusion';

const HISTORY_MS = 2800;
const MIC_CALIBRATION_MS = 1200;
const HYSTERESIS = 4;
const GAP_HOLD_MS = 2600;
const ACTIVE_CONFIDENCE = 10;
const CODE_FREQS = [400, 500, 600, 700, 800, 900, 1000, 2000, 2300, 2600, 2900];

interface HistorySample {
  t: number;
  wall: number;
  value: number;
}

interface InternalEmitterState {
  confidence: number;
  audioConfidence: number;
  stability: number;
  zone: Zone;
  history: HistorySample[];
  levelScore: number;
  pairScore: number;
  rhythmScore: number;
  energy: number;
  lastSignalAt: number;
}

export class AudioZoneTracker {
  private readonly state = new Map<string, InternalEmitterState>();
  private calibrationUntil = 0;
  private calibrationLevels: number[] = [];
  private levelDb = -120;
  private noiseFloorDb = -68;
  private status: ReceiverStatus = 'idle';

  constructor(private readonly emitters: EmitterFingerprint[] = EMITTERS) {
    for (const emitter of emitters) {
      this.state.set(emitter.id, {
        confidence: 0,
        audioConfidence: 0,
        stability: 0,
        zone: 'far',
        history: [],
        levelScore: 0,
        pairScore: 0,
        rhythmScore: 0,
        energy: 0,
        lastSignalAt: 0
      });
    }
  }

  startCalibration(nowMs: number): void {
    this.calibrationUntil = nowMs + MIC_CALIBRATION_MS;
    this.calibrationLevels = [];
    this.levelDb = -120;
    this.noiseFloorDb = -68;
    this.status = 'calibrating';
    this.resetEmitterState();
  }

  stop(): void {
    this.status = 'idle';
    this.calibrationUntil = 0;
    this.calibrationLevels = [];
    this.resetEmitterState();
  }

  process(input: Float32Array, sampleRate: number, audioTimeSeconds: number, nowMs: number): ZoneSnapshot {
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

    const codedEnergy = codedBandEnergy(input, sampleRate);
    const energies = this.emitters.map((emitter) => ({ emitter, energy: codedEnergy }));
    const maxEnergy = Math.max(...energies.map((item) => item.energy), 1e-9);
    const levelOverNoise = Math.max(0, this.levelDb - this.noiseFloorDb);
    const signalPresence = clamp((levelOverNoise - 1.5) / 6, 0, 1);

    for (const item of energies) {
      const entry = this.requireState(item.emitter.id);
      entry.energy = item.energy;
      entry.levelScore = clamp((levelOverNoise - 2) / 18, 0, 1);
      entry.pairScore = clamp(item.energy / maxEnergy, 0, 1) * signalPresence;
      entry.history.push({ t: audioTimeSeconds, wall: nowMs, value: item.energy / maxEnergy });
      while (entry.history.length > 0 && nowMs - entry.history[0].wall > HISTORY_MS) {
        entry.history.shift();
      }
      entry.rhythmScore = rhythmScore(entry.history, item.emitter.pulseHz) * signalPresence;

      const rawAudio = 100 * (entry.levelScore * 0.48 + entry.pairScore * 0.34 + entry.rhythmScore * 0.18);
      const emitterPresent = signalPresence > 0.22 && entry.energy > 0.0025;
      if (emitterPresent) {
        entry.lastSignalAt = nowMs;
        entry.audioConfidence = entry.audioConfidence * 0.76 + rawAudio * 0.24;
      } else if (nowMs - entry.lastSignalAt <= GAP_HOLD_MS) {
        entry.audioConfidence *= 0.995;
      } else {
        entry.audioConfidence = entry.audioConfidence * 0.86 + rawAudio * 0.14;
        if (entry.audioConfidence < 8 || levelOverNoise < 2) entry.audioConfidence *= 0.9;
      }

      const candidateZone = zoneForConfidence(entry.audioConfidence, entry.zone);
      entry.stability = updateStability(entry.stability, candidateZone === entry.zone, entry.audioConfidence);
      entry.zone = candidateZone;
      entry.confidence = combineConfidence({
        audio: entry.audioConfidence,
        stability: entry.stability
      });
    }

    const snapshot = this.snapshot();
    this.status = snapshot.active ? 'locked' : 'listening';
    return { ...snapshot, status: this.status };
  }

  snapshot(): ZoneSnapshot {
    const emitters = this.emitters.map((emitter) => toEstimate(emitter, this.requireState(emitter.id)));
    const active = [...emitters].sort((a, b) => b.confidence - a.confidence)[0] ?? null;
    return {
      status: active && active.confidence >= ACTIVE_CONFIDENCE ? this.status : this.status === 'locked' ? 'listening' : this.status,
      active: active && active.confidence >= ACTIVE_CONFIDENCE ? active : null,
      emitters,
      levelDb: this.levelDb,
      noiseFloorDb: this.noiseFloorDb
    };
  }

  private requireState(emitterId: string): InternalEmitterState {
    const entry = this.state.get(emitterId);
    if (!entry) throw new Error(`missing emitter state for ${emitterId}`);
    return entry;
  }

  private resetEmitterState(): void {
    for (const entry of this.state.values()) {
      entry.confidence = 0;
      entry.audioConfidence = 0;
      entry.stability = 0;
      entry.zone = 'far';
      entry.history = [];
      entry.levelScore = 0;
      entry.pairScore = 0;
      entry.rhythmScore = 0;
      entry.energy = 0;
      entry.lastSignalAt = 0;
    }
  }
}

function toEstimate(emitter: EmitterFingerprint, entry: InternalEmitterState): EmitterEstimate {
  return {
    emitter,
    zone: entry.zone,
    confidence: entry.confidence,
    audioConfidence: entry.audioConfidence,
    stability: entry.stability,
    levelScore: entry.levelScore,
    pairScore: entry.pairScore,
    rhythmScore: entry.rhythmScore
  };
}

function rhythmScore(history: HistorySample[], pulseHz: number): number {
  if (pulseHz <= 0) return 0;
  if (history.length < 8) return 0;
  const mean = history.reduce((sum, item) => sum + item.value, 0) / history.length;
  let sin = 0;
  let cos = 0;
  let total = 0;
  for (const item of history) {
    const value = Math.max(0, item.value - mean);
    const phase = 2 * Math.PI * pulseHz * item.t;
    sin += value * Math.sin(phase);
    cos += value * Math.cos(phase);
    total += Math.abs(value);
  }
  return clamp((Math.sqrt(sin * sin + cos * cos) / (total + 1e-9)) * 2.4, 0, 1);
}

function codedBandEnergy(input: Float32Array, sampleRate: number): number {
  let sum = 0;
  for (const frequency of CODE_FREQS) {
    sum += goertzel(input, sampleRate, frequency);
  }
  return sum / CODE_FREQS.length;
}

function zoneForConfidence(confidence: number, previousZone: Zone): Zone {
  let candidate: Zone = 'far';
  if (confidence >= ZONE_THRESHOLDS.close) candidate = 'close';
  else if (confidence >= ZONE_THRESHOLDS.near) candidate = 'near';
  else if (confidence >= ZONE_THRESHOLDS.mid) candidate = 'mid';
  else if (confidence >= ZONE_THRESHOLDS.far) candidate = 'far';

  const previousIndex = ZONES.indexOf(previousZone);
  const candidateIndex = ZONES.indexOf(candidate);
  if (previousIndex < 0 || candidateIndex === previousIndex) return candidate;

  if (candidateIndex > previousIndex) {
    return confidence >= ZONE_THRESHOLDS[candidate] + HYSTERESIS ? candidate : previousZone;
  }
  const currentThreshold = ZONE_THRESHOLDS[previousZone] || 0;
  return confidence < currentThreshold - HYSTERESIS ? candidate : previousZone;
}

function updateStability(previous: number, sameZone: boolean, audioConfidence: number): number {
  if (audioConfidence < 12) return Math.max(0, previous - 8);
  return clamp(previous + (sameZone ? 3 : -5), 0, 100);
}
