from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean
from time import monotonic


class Zone(str, Enum):
    VERY_NEAR = "very_near"
    NEAR = "near"
    MID = "mid"
    FAR = "far"


ZONE_ORDER = [Zone.VERY_NEAR, Zone.NEAR, Zone.MID, Zone.FAR]

ZONE_LABELS = {
    Zone.VERY_NEAR: "very near",
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
