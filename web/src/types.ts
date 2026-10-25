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

// Framed chirps are an intelligent message. Unframed ones are a clock when a
// single channel ticks at a steady period, and noise otherwise.
export type ReceptionKind = 'noise' | 'clock' | 'intelligent';

export interface Reception {
  kind: ReceptionKind;
  text: string;
}

export interface TranslationSnapshot {
  title: string;
  verdict: 'DEAD' | 'NOISE' | 'CLOCK' | 'ALIVE';
  // The latest intelligent message, or '---'.
  message: string;
  // The reception in progress, if any.
  live: Reception | null;
  stream: string;
  pair: string;
}
