from experience_model import (
    SourceObservation,
    SourceSelector,
    Zone,
    content_for_zone,
    parse_zone,
    snapshot_for_source,
    zone_from_rssi,
)


def test_rssi_zone_thresholds():
    assert zone_from_rssi(-42) == Zone.VERY_NEAR
    assert zone_from_rssi(-58) == Zone.NEAR
    assert zone_from_rssi(-72) == Zone.MID
    assert zone_from_rssi(-88) == Zone.FAR


def test_zone_parser_accepts_demo_shortcuts():
    assert parse_zone("very near") == Zone.VERY_NEAR
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


def run_tests():
    tests = [
        test_rssi_zone_thresholds,
        test_zone_parser_accepts_demo_shortcuts,
        test_source_selection_holds_against_small_jumps,
        test_reveal_is_controlled_by_source_zone_mapping,
    ]
    for test in tests:
        test()
        print(f"{test.__name__}: OK")
    print(f"Result: {len(tests)} passed, 0 failed")


if __name__ == "__main__":
    run_tests()
