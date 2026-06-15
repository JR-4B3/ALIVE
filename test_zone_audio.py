import numpy as np

from zone_audio import (
    EMITTER_FINGERPRINTS,
    ZoneEmitterPlayer,
    fingerprint_for,
    normalize_zone,
    synthesize_emitter_block,
)


def test_zone_aliases():
    assert normalize_zone("far") == "far"
    assert normalize_zone("middle") == "mid"
    assert normalize_zone("very near") == "close"
    assert normalize_zone("c") == "close"


def test_fingerprint_lookup_defaults_to_first_emitter():
    assert fingerprint_for("emitter-3").emitter_id == "emitter-3"
    assert fingerprint_for("missing").emitter_id == EMITTER_FINGERPRINTS[0].emitter_id


def test_zone_blocks_have_audio_and_scale_by_zone():
    fingerprint = fingerprint_for("emitter-1")
    far = synthesize_emitter_block(fingerprint, "far", start_frame=0, frames=4096)
    close = synthesize_emitter_block(fingerprint, "close", start_frame=0, frames=4096)

    assert far.dtype == np.float32
    assert len(far) == 4096
    assert np.max(np.abs(far)) > 0
    assert np.sqrt(np.mean(close * close)) > np.sqrt(np.mean(far * far))


def test_player_applies_phone_zone_update():
    player = ZoneEmitterPlayer()
    player.apply_phone_zone("emitter-4", "near", 76)
    snapshot = player.snapshot()

    assert snapshot["mode"] == "zone"
    assert snapshot["emitterId"] == "emitter-4"
    assert snapshot["zone"] == "near"
    assert snapshot["lastPhoneUpdate"]["confidence"] == 76.0


def run_tests():
    tests = [
        test_zone_aliases,
        test_fingerprint_lookup_defaults_to_first_emitter,
        test_zone_blocks_have_audio_and_scale_by_zone,
        test_player_applies_phone_zone_update,
    ]
    for test in tests:
        test()
        print(f"{test.__name__}: OK")
    print(f"Result: {len(tests)} passed, 0 failed")


if __name__ == "__main__":
    run_tests()
