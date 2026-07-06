export type ReceiverStatus =
  | 'idle'
  | 'requesting'
  | 'calibrating'
  | 'listening'
  | 'mic-blocked';

export interface SignalLevelSnapshot {
  status: ReceiverStatus;
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
