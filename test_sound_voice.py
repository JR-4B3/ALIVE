import base64
import copy

import numpy as np
import pytest

from sound_voice import (RATE, LETTERS, compile_voice, features, generated_sounds,
                         identify, pcm_for, render_message, stamp, validate_voice)


@pytest.fixture(scope='module')
def voice():
    t = np.arange(int(RATE * .24)) / RATE
    phase = 2 * np.pi * np.cumsum(820 + 1100 * t + 160 * np.sin(t * 27)) / RATE
    source = np.sin(np.pi * np.arange(len(t)) / len(t)) ** .7 * (np.sin(phase) + .28 * np.sin(phase * 2.71)) * .5
    return compile_voice(generated_sounds(source), 'Test voice')


def test_generated_alphabet_is_distinct(voice):
    for ch in LETTERS:
        assert identify(features(pcm_for(voice, ch)), voice)['symbol'] == ch


def test_package_integrity_and_pcm_validation(voice):
    assert validate_voice(voice)['id'] == voice['id']
    changed = copy.deepcopy(voice)
    changed['name'] = 'Tampered'
    with pytest.raises(ValueError, match='version ID'):
        validate_voice(changed)
    changed = copy.deepcopy(voice)
    changed['symbols']['A']['pcm'] = base64.b64encode(b'\0\0').decode()
    with pytest.raises(ValueError, match='PCM'):
        validate_voice(stamp(changed))


def test_revision_changes_id_and_retains_samples(voice):
    changed = copy.deepcopy(voice)
    changed['symbols']['A']['templates'].append(features(pcm_for(voice, 'A') * .1))
    assert stamp(changed)['id'] != voice['id']
    assert changed['symbols']['A']['pcm'] == voice['symbols']['A']['pcm']
    assert len(voice['symbols']['A']['templates']) == 1


def test_invalid_source_and_message_rejected(voice):
    with pytest.raises(ValueError):
        compile_voice({}, 'Incomplete')
    with pytest.raises(ValueError, match='silent'):
        compile_voice({ch: np.zeros(RATE) for ch in LETTERS}, 'Silent')
    with pytest.raises(ValueError):
        render_message(voice, '123')
