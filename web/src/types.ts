export type Zone = 'far' | 'mid' | 'near' | 'close';

export type ReceiverStatus =
  | 'idle'
  | 'requesting'
  | 'calibrating'
  | 'listening'
  | 'locked'
  | 'mic-blocked'
  | 'control-offline';

export interface EmitterFingerprint {
  id: string;
  label: string;
  low: number;
  high: number;
  pulseHz: number;
}

export interface ConfidenceInputs {
  audio: number;
  camera?: number;
  ble?: number;
  stability: number;
}

export interface EmitterEstimate {
  emitter: EmitterFingerprint;
  zone: Zone;
  confidence: number;
  audioConfidence: number;
  stability: number;
  levelScore: number;
  pairScore: number;
  rhythmScore: number;
}

export interface ZoneSnapshot {
  status: ReceiverStatus;
  active: EmitterEstimate | null;
  emitters: EmitterEstimate[];
  levelDb: number;
  noiseFloorDb: number;
}

export interface TranslationSnapshot {
  title: string;
  verdict: 'DEAD' | 'CLOCK' | 'UNKNOWN' | 'ALIVE';
  message: string;
  stream: string;
  pair: string;
}

export interface ControllerPayload {
  emitterId: string;
  zone: Zone;
  confidence: number;
  levels: Record<string, { zone: Zone; confidence: number }>;
  message: string;
}
