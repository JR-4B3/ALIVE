from experience_model import (
    SourceObservation,
    SourceSelector,
    Zone,
    content_for_audio_zone,
    content_for_zone,
    parse_zone,
    snapshot_for_audio_observation,
    snapshot_for_ble_observation,
    snapshot_for_fused_observation,
    snapshot_for_source,
    zone_from_ble_rssi,
    zone_from_score,
    zone_score,
    zone_from_signal_level,
    zone_from_rssi,
)


def test_rssi_zone_thresholds():
    assert zone_from_rssi(-42) == Zone.VERY_NEAR
    assert zone_from_rssi(-58) == Zone.NEAR
    assert zone_from_rssi(-72) == Zone.MID
    assert zone_from_rssi(-88) == Zone.FAR


def test_ble_rssi_uses_shared_zone_thresholds():
    assert zone_from_ble_rssi(-45) == Zone.VERY_NEAR
    assert zone_from_ble_rssi(-59) == Zone.NEAR
    assert zone_from_ble_rssi(-74) == Zone.MID
    assert zone_from_ble_rssi(-90) == Zone.FAR


def test_audio_signal_zone_thresholds():
    assert zone_from_signal_level(-34) == Zone.VERY_NEAR
    assert zone_from_signal_level(-48) == Zone.NEAR
    assert zone_from_signal_level(-62) == Zone.MID
    assert zone_from_signal_level(-76) == Zone.FAR


def test_zone_parser_accepts_demo_shortcuts():
    assert parse_zone("very near") == Zone.VERY_NEAR
    assert parse_zone("close") == Zone.VERY_NEAR
    assert parse_zone("vn") == Zone.VERY_NEAR
    assert parse_zone("mid") == Zone.MID


def test_source_selection_holds_against_small_jumps():
    selector = SourceSelector(switch_margin_db=6, hold_count=1)
    selector.observe(SourceObservation("A", -60))
    selector.observe(SourceObservation("B", -57))
    assert selector.selected.source_id == "A"
    selector.observe(SourceObservation("B", -45))
    assert selector.selected.source_id == "B"


def test_reveal_is_controlled_by_source_zone_mapping():
    selector = SourceSelector(hold_count=1)
    selector.observe(SourceObservation("ALIVE-T480", -72))
    selector.observe(SourceObservation("ALIVE-T480", -72))
    selected = selector.selected
    snapshot = snapshot_for_source(selected, Zone.MID)
    assert snapshot["sourceId"] == "ALIVE-T480"
    assert snapshot["zone"] == "mid"
    assert snapshot["content"]["revealed"] is True

    fragment = content_for_zone(Zone.FAR, Zone.MID)
    assert fragment["revealed"] is False


def test_audio_snapshot_reveals_only_when_heard_zone_matches():
    snapshot = snapshot_for_audio_observation(
        source_id="ALIVE-T480",
        zone=Zone.NEAR,
        signal_level_db=-47.2,
        smoothed_signal_level_db=-48.1,
        confidence=0.82,
        mic_active=True,
        reveal_zone=Zone.NEAR,
    )
    assert snapshot["mode"] == "audio"
    assert snapshot["sourceId"] == "ALIVE-T480"
    assert snapshot["zone"] == "near"
    assert snapshot["content"]["revealed"] is True

    no_lock = content_for_audio_zone(Zone.NEAR, Zone.NEAR, confidence=0.05, mic_active=True)
    assert no_lock["revealed"] is False
    assert no_lock["kind"] == "dead"


def test_ble_snapshot_and_fused_snapshot():
    ble = snapshot_for_ble_observation(
        source_id="ALIVE-T480",
        zone=Zone.VERY_NEAR,
        raw_rssi=-47,
        smoothed_rssi=-49,
        confidence=0.8,
        ble_active=True,
        reveal_zone=Zone.VERY_NEAR,
    )
    assert ble["mode"] == "ble"
    assert ble["zone"] == "close"
    assert ble["content"]["revealed"] is True

    fused = snapshot_for_fused_observation(
        source_id="ALIVE-T480",
        zone=zone_from_score((zone_score(Zone.NEAR) + zone_score(Zone.MID)) / 2),
        confidence=0.7,
        reveal_zone=Zone.NEAR,
        ble_active=True,
        mic_active=True,
        raw_rssi=-59,
        smoothed_rssi=-60,
        signal_level_db=-61,
        smoothed_signal_level_db=-62,
        ble_confidence=0.75,
        audio_confidence=0.65,
    )
    assert fused["mode"] == "ble_audio"
    assert fused["bleActive"] is True
    assert fused["micActive"] is True


def run_tests():
    tests = [
        test_rssi_zone_thresholds,
        test_ble_rssi_uses_shared_zone_thresholds,
        test_audio_signal_zone_thresholds,
        test_zone_parser_accepts_demo_shortcuts,
        test_source_selection_holds_against_small_jumps,
        test_reveal_is_controlled_by_source_zone_mapping,
        test_audio_snapshot_reveals_only_when_heard_zone_matches,
        test_ble_snapshot_and_fused_snapshot,
    ]
    for test in tests:
        test()
        print(f"{test.__name__}: OK")
    print(f"Result: {len(tests)} passed, 0 failed")


if __name__ == "__main__":
    run_tests()
