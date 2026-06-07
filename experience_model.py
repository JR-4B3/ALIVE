from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean
from time import monotonic


class Zone(str, Enum):
    VERY_NEAR = "close"
    NEAR = "near"
    MID = "mid"
    FAR = "far"


ZONE_ORDER = [Zone.VERY_NEAR, Zone.NEAR, Zone.MID, Zone.FAR]

ZONE_LABELS = {
    Zone.VERY_NEAR: "close",
    Zone.NEAR: "near",
    Zone.MID: "mid",
    Zone.FAR: "far",
}

ZONE_RSSI = {
    Zone.VERY_NEAR: -42,
    Zone.NEAR: -58,
    Zone.MID: -72,
    Zone.FAR: -86,
}

SIGNAL_LEVEL_DB = {
    Zone.VERY_NEAR: -34,
    Zone.NEAR: -48,
    Zone.MID: -62,
    Zone.FAR: -76,
}

ZONE_COPY = {
    Zone.VERY_NEAR: {
        "title": "Signal saturating",
        "body": "The source is almost under the phone. Patterns become crisp, but the receiver is overloaded at the edges.",
    },
    Zone.NEAR: {
        "title": "Signal resolving",
        "body": "The carrier separates from the room noise. Fragments align into repeatable structure.",
    },
    Zone.MID: {
        "title": "Stable corridor",
        "body": "The source is present but partly veiled. The app holds the signal and waits for a stronger lock.",
    },
    Zone.FAR: {
        "title": "Distant trace",
        "body": "Only a weak source identity is visible. Most of the message remains below the noise floor.",
    },
}

REVEALED_MESSAGE = "WE ARE STILL HERE"


def parse_zone(value: str) -> Zone:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "very": Zone.VERY_NEAR,
        "verynear": Zone.VERY_NEAR,
        "very_near": Zone.VERY_NEAR,
        "close": Zone.VERY_NEAR,
        "c": Zone.VERY_NEAR,
        "vn": Zone.VERY_NEAR,
        "near": Zone.NEAR,
        "n": Zone.NEAR,
        "mid": Zone.MID,
        "middle": Zone.MID,
        "m": Zone.MID,
        "far": Zone.FAR,
        "f": Zone.FAR,
    }
    if normalized not in aliases:
        valid = ", ".join(zone.value for zone in ZONE_ORDER)
        raise ValueError(f"unknown zone '{value}' (valid: {valid})")
    return aliases[normalized]


def zone_from_rssi(rssi: float) -> Zone:
    if rssi >= -50:
        return Zone.VERY_NEAR
    if rssi >= -65:
        return Zone.NEAR
    if rssi >= -80:
        return Zone.MID
    return Zone.FAR


def zone_from_ble_rssi(rssi: float) -> Zone:
    return zone_from_rssi(rssi)


def zone_from_signal_level(level_db: float) -> Zone:
    if level_db >= -42:
        return Zone.VERY_NEAR
    if level_db >= -55:
        return Zone.NEAR
    if level_db >= -68:
        return Zone.MID
    return Zone.FAR


def zone_from_score(score: float) -> Zone:
    if score >= 0.58:
        return Zone.VERY_NEAR
    if score >= 0.42:
        return Zone.NEAR
    if score >= 0.25:
        return Zone.MID
    return Zone.FAR


def zone_score(zone: Zone) -> float:
    return {
        Zone.VERY_NEAR: 0.88,
        Zone.NEAR: 0.64,
        Zone.MID: 0.38,
        Zone.FAR: 0.10,
    }[zone]


@dataclass
class ZoneStabilizer:
    stable_zone: Zone = Zone.FAR
    candidate_zone: Zone = Zone.FAR
    candidate_count: int = 0
    hold_count: int = 3

    def update(self, candidate: Zone) -> Zone:
        if candidate == self.stable_zone:
            self.candidate_zone = candidate
            self.candidate_count = 0
            return self.stable_zone
        if candidate == self.candidate_zone:
            self.candidate_count += 1
        else:
            self.candidate_zone = candidate
            self.candidate_count = 1
        if self.candidate_count >= self.hold_count:
            self.stable_zone = candidate
            self.candidate_count = 0
        return self.stable_zone


@dataclass
class RssiSmoother:
    window_size: int = 6
    values: deque[float] = field(default_factory=deque)

    def add(self, rssi: float) -> float:
        self.values.append(float(rssi))
        while len(self.values) > self.window_size:
            self.values.popleft()
        return self.value

    @property
    def value(self) -> float:
        if not self.values:
            return -100.0
        return mean(self.values)


@dataclass
class SourceObservation:
    source_id: str
    rssi: float
    seen_at: float = field(default_factory=monotonic)


@dataclass
class SourceState:
    source_id: str
    smoother: RssiSmoother = field(default_factory=RssiSmoother)
    last_raw_rssi: float = -100.0
    last_seen: float = field(default_factory=monotonic)
    stable_zone: Zone = Zone.FAR
    candidate_zone: Zone = Zone.FAR
    candidate_count: int = 0

    def observe(self, rssi: float, hold_count: int = 2) -> None:
        self.last_raw_rssi = float(rssi)
        self.last_seen = monotonic()
        smoothed = self.smoother.add(rssi)
        next_zone = zone_from_rssi(smoothed)
        if next_zone == self.stable_zone:
            self.candidate_zone = next_zone
            self.candidate_count = 0
            return
        if next_zone == self.candidate_zone:
            self.candidate_count += 1
        else:
            self.candidate_zone = next_zone
            self.candidate_count = 1
        if self.candidate_count >= hold_count:
            self.stable_zone = next_zone
            self.candidate_count = 0

    @property
    def smoothed_rssi(self) -> float:
        return self.smoother.value

    @property
    def score(self) -> float:
        age_penalty = max(0.0, monotonic() - self.last_seen) * 4.0
        return self.smoothed_rssi - age_penalty


class SourceSelector:
    def __init__(
        self,
        switch_margin_db: float = 6.0,
        stale_after_s: float = 4.0,
        hold_count: int = 2,
    ) -> None:
        self.switch_margin_db = switch_margin_db
        self.stale_after_s = stale_after_s
        self.hold_count = hold_count
        self.sources: dict[str, SourceState] = {}
        self.selected_source_id: str | None = None

    def observe(self, observation: SourceObservation) -> SourceState:
        state = self.sources.get(observation.source_id)
        if state is None:
            state = SourceState(source_id=observation.source_id)
            self.sources[observation.source_id] = state
        state.observe(observation.rssi, hold_count=self.hold_count)
        self._drop_stale()
        self._select()
        return state

    @property
    def selected(self) -> SourceState | None:
        if self.selected_source_id is None:
            return None
        return self.sources.get(self.selected_source_id)

    def _drop_stale(self) -> None:
        now = monotonic()
        stale = [
            source_id
            for source_id, state in self.sources.items()
            if now - state.last_seen > self.stale_after_s
        ]
        for source_id in stale:
            self.sources.pop(source_id, None)
            if self.selected_source_id == source_id:
                self.selected_source_id = None

    def _select(self) -> None:
        if not self.sources:
            self.selected_source_id = None
            return
        best = max(self.sources.values(), key=lambda state: state.score)
        current = self.selected
        if current is None:
            self.selected_source_id = best.source_id
            return
        if best.source_id == current.source_id:
            return
        if best.score >= current.score + self.switch_margin_db:
            self.selected_source_id = best.source_id


def content_for_zone(zone: Zone, reveal_zone: Zone) -> dict[str, str | bool]:
    if zone == reveal_zone:
        return {
            "kind": "revealed",
            "title": "Message locked",
            "body": REVEALED_MESSAGE,
            "revealed": True,
        }

    copy = ZONE_COPY[zone]
    return {
        "kind": "fragment",
        "title": copy["title"],
        "body": copy["body"],
        "revealed": False,
    }


def content_for_audio_zone(
    zone: Zone | None, reveal_zone: Zone, confidence: float, mic_active: bool
) -> dict[str, str | bool]:
    return content_for_sensor_zone(
        zone=zone,
        reveal_zone=reveal_zone,
        confidence=confidence,
        active=mic_active,
        inactive_title="Microphone not active",
        inactive_body="Start microphone sensing so the phone can estimate distance from the laptop beacon.",
        no_lock_body="The receiver hears the room, but the beacon is below the lock threshold.",
    )


def content_for_sensor_zone(
    zone: Zone | None,
    reveal_zone: Zone,
    confidence: float,
    active: bool,
    inactive_title: str,
    inactive_body: str,
    no_lock_body: str,
) -> dict[str, str | bool]:
    if not active:
        return {
            "kind": "inactive",
            "title": inactive_title,
            "body": inactive_body,
            "revealed": False,
        }
    if zone is None or confidence < 0.18:
        return {
            "kind": "dead",
            "title": "No stable beacon",
            "body": no_lock_body,
            "revealed": False,
        }
    if zone == reveal_zone:
        return content_for_zone(zone, reveal_zone)
    copy = ZONE_COPY[zone]
    return {
        "kind": "fragment",
        "title": copy["title"],
        "body": copy["body"],
        "revealed": False,
    }


def snapshot_for_ble_observation(
    source_id: str,
    zone: Zone | None,
    raw_rssi: float | None,
    smoothed_rssi: float | None,
    confidence: float,
    ble_active: bool,
    reveal_zone: Zone,
) -> dict[str, object]:
    return {
        "mode": "ble",
        "sourceId": source_id if ble_active else None,
        "zone": zone.value if zone is not None else None,
        "zoneLabel": ZONE_LABELS[zone] if zone is not None else "no lock",
        "revealZone": reveal_zone.value,
        "revealZoneLabel": ZONE_LABELS[reveal_zone],
        "rawRssi": None if raw_rssi is None else round(raw_rssi, 1),
        "smoothedRssi": None if smoothed_rssi is None else round(smoothed_rssi, 1),
        "signalLevelDb": None,
        "smoothedSignalLevelDb": None,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "bleConfidence": round(max(0.0, min(1.0, confidence)), 2),
        "audioConfidence": 0.0,
        "bleActive": ble_active,
        "micActive": False,
        "content": content_for_sensor_zone(
            zone=zone,
            reveal_zone=reveal_zone,
            confidence=confidence,
            active=ble_active,
            inactive_title="BLE scan not active",
            inactive_body="Start BLE-only mode so the phone can read laptop advertisements and RSSI.",
            no_lock_body="The phone is scanning, but the laptop advertisement is not stable enough yet.",
        ),
    }


def snapshot_for_fused_observation(
    source_id: str,
    zone: Zone | None,
    confidence: float,
    reveal_zone: Zone,
    ble_active: bool,
    mic_active: bool,
    raw_rssi: float | None,
    smoothed_rssi: float | None,
    signal_level_db: float | None,
    smoothed_signal_level_db: float | None,
    ble_confidence: float,
    audio_confidence: float,
) -> dict[str, object]:
    active = ble_active or mic_active
    return {
        "mode": "ble_audio",
        "sourceId": source_id if active else None,
        "zone": zone.value if zone is not None else None,
        "zoneLabel": ZONE_LABELS[zone] if zone is not None else "no lock",
        "revealZone": reveal_zone.value,
        "revealZoneLabel": ZONE_LABELS[reveal_zone],
        "rawRssi": None if raw_rssi is None else round(raw_rssi, 1),
        "smoothedRssi": None if smoothed_rssi is None else round(smoothed_rssi, 1),
        "signalLevelDb": None if signal_level_db is None else round(signal_level_db, 1),
        "smoothedSignalLevelDb": None
        if smoothed_signal_level_db is None
        else round(smoothed_signal_level_db, 1),
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "bleConfidence": round(max(0.0, min(1.0, ble_confidence)), 2),
        "audioConfidence": round(max(0.0, min(1.0, audio_confidence)), 2),
        "bleActive": ble_active,
        "micActive": mic_active,
        "content": content_for_sensor_zone(
            zone=zone,
            reveal_zone=reveal_zone,
            confidence=confidence,
            active=active,
            inactive_title="Sensors not active",
            inactive_body="Start BLE + audio mode so the phone can combine RSSI and microphone signal.",
            no_lock_body="The receiver is active, but neither BLE nor audio is stable enough for a lock.",
        ),
    }


def snapshot_for_audio_observation(
    source_id: str,
    zone: Zone | None,
    signal_level_db: float | None,
    smoothed_signal_level_db: float | None,
    confidence: float,
    mic_active: bool,
    reveal_zone: Zone,
) -> dict[str, object]:
    return {
        "mode": "audio",
        "sourceId": source_id if mic_active else None,
        "zone": zone.value if zone is not None else None,
        "zoneLabel": ZONE_LABELS[zone] if zone is not None else "no lock",
        "revealZone": reveal_zone.value,
        "revealZoneLabel": ZONE_LABELS[reveal_zone],
        "signalLevelDb": None
        if signal_level_db is None
        else round(signal_level_db, 1),
        "smoothedSignalLevelDb": None
        if smoothed_signal_level_db is None
        else round(smoothed_signal_level_db, 1),
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "audioConfidence": round(max(0.0, min(1.0, confidence)), 2),
        "bleConfidence": 0.0,
        "rawRssi": None,
        "smoothedRssi": None,
        "bleActive": False,
        "micActive": mic_active,
        "content": content_for_audio_zone(zone, reveal_zone, confidence, mic_active),
    }


def snapshot_for_source(source: SourceState | None, reveal_zone: Zone) -> dict[str, object]:
    if source is None:
        return {
            "sourceId": None,
            "rawRssi": None,
            "smoothedRssi": None,
            "zone": None,
            "zoneLabel": "no source",
            "revealZone": reveal_zone.value,
            "revealZoneLabel": ZONE_LABELS[reveal_zone],
            "content": {
                "kind": "none",
                "title": "No source selected",
                "body": "Waiting for a stable source identity.",
                "revealed": False,
            },
        }

    zone = source.stable_zone
    return {
        "sourceId": source.source_id,
        "rawRssi": round(source.last_raw_rssi, 1),
        "smoothedRssi": round(source.smoothed_rssi, 1),
        "zone": zone.value,
        "zoneLabel": ZONE_LABELS[zone],
        "revealZone": reveal_zone.value,
        "revealZoneLabel": ZONE_LABELS[reveal_zone],
        "content": content_for_zone(zone, reveal_zone),
    }
