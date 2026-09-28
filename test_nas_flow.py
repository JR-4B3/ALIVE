import json
import threading
import urllib.error
import urllib.request
from unittest.mock import patch

from emitter import ApiState, QuietThreadingHTTPServer, make_handler
from reply_engine import signal_duration_seconds


def test_esp32_duration_matches_audio_including_rounded_gaps():
    # HI: 2 * 220 ms tones + 293/325 ms gaps + 50 ms lead + 1000 ms tail.
    assert signal_duration_seconds("HI") == 2.108
    # The short A gap is clamped to 220 ms for reliable microphone decoding.
    assert signal_duration_seconds("A") == 1.49
    assert signal_duration_seconds("A A") == 3.19


def test_public_replay_deadline_uses_firmware_duration():
    state = ApiState("HI")
    with patch("emitter.time.monotonic", return_value=1000):
        state.note_device_poll()
        assert state.reserve_public_play() == 0
        payload = state.play_current_once()
        assert payload["duration"] == 2.108
        assert payload["replayAfterSeconds"] == 2.608
    with patch("emitter.time.monotonic", return_value=1002.60):
        assert state.reserve_public_play() == 1
    with patch("emitter.time.monotonic", return_value=1002.61):
        assert state.reserve_public_play() == 0


def test_wifi_command_persists_across_restart(tmp_path):
    file = tmp_path / "state.json"
    state = ApiState("HELLO", state_file=file)
    state.set_reply("I AM HERE")
    assert state.current_emitter_message()["revision"] == 0
    assert state.current_emitter_message()["deviceOnline"] is False
    state.note_device_poll()
    assert state.play_current_once()["revision"] == 1
    restored = ApiState("HELLO", state_file=file)
    assert restored.current_emitter_message()["message"] == "I AM HERE"
    assert restored.current_emitter_message()["revision"] == 1
    restored.note_device_poll()
    assert restored.play_current_once()["revision"] == 2
    assert restored.reset_reply()["message"] == "HELLO"
    assert ApiState("HELLO",
                     state_file=file).current_emitter_message()["message"] == "HELLO"


def test_web_and_device_use_separate_tokens_and_restricted_origin():
    state = ApiState("HELLO")
    environment = {"ALIVE_WEB_TOKEN": "web-secret", "ALIVE_DEVICE_TOKEN": "device-secret",
                   "ALIVE_WEB_ORIGIN": "https://site.example"}
    with patch.dict("os.environ", environment):
        server = QuietThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"

            def request(path, token, origin=None, method="GET"):
                headers = {"Authorization": f"Bearer {token}"}
                if origin:
                    headers["Origin"] = origin
                return urllib.request.urlopen(urllib.request.Request(base + path,
                    headers=headers, method=method), timeout=2)

            try:
                request("/api/emitter/main/play", "web-secret", method="POST")
                assert False, "An offline device must not receive a queued play command"
            except urllib.error.HTTPError as error:
                assert error.code == 503
                assert json.load(error)["error"].startswith("ESP32 is offline")
            with request("/api/emitter/main/current", "device-secret") as response:
                assert json.load(response)["revision"] == 0
            try:
                request("/api/emitter/main/current", "web-secret")
                assert False, "Web token must not act as an ESP32"
            except urllib.error.HTTPError as error:
                assert error.code == 401
            with request("/api/emitter/main/play", "web-secret", "https://site.example", "POST") as response:
                assert json.load(response)["revision"] == 1
                assert response.headers["Access-Control-Allow-Origin"] == "https://site.example"
            state.set_reply("I AM HERE")
            with request("/api/emitter/main/reset", "web-secret", method="POST") as response:
                assert json.load(response)["message"] == "HELLO"
            try:
                request("/api/emitter/main/reset", "device-secret", method="POST")
                assert False, "Device token must not reset the prepared message"
            except urllib.error.HTTPError as error:
                assert error.code == 401
            with request("/api/emitter/main/play", "web-secret", "https://other.example", "POST") as response:
                assert "Access-Control-Allow-Origin" not in response.headers
            try:
                request("/api/emitter/main/play", "device-secret", method="POST")
                assert False, "Device token must not trigger playback"
            except urllib.error.HTTPError as error:
                assert error.code == 401
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def test_public_exhibition_page_can_send_and_play_with_bounded_requests():
    state = ApiState("HELLO")
    environment = {"ALIVE_WEB_TOKEN": "operator-secret", "ALIVE_DEVICE_TOKEN": "device-secret",
                   "ALIVE_WEB_ORIGIN": "https://site.example", "ALIVE_PUBLIC_DEMO": "1"}
    with patch.dict("os.environ", environment), patch("emitter.generate_reply", return_value="I AM HERE"):
        server = QuietThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"

            def post(path, payload=None):
                data = json.dumps(payload or {}).encode()
                return urllib.request.urlopen(urllib.request.Request(base + path, data=data,
                    headers={"Origin": "https://site.example", "Content-Type": "application/json"},
                    method="POST"), timeout=2)

            with post("/api/message", {"message": "Are you there?"}) as response:
                assert json.load(response)["reply"] == "I AM HERE"
            try:
                post("/api/emitter/main/reset")
                assert False, "Public visitors must not reset the prepared message"
            except urllib.error.HTTPError as error:
                assert error.code == 401
            try:
                post("/api/message", {"message": "Again"})
                assert False, "Public LLM calls must be rate limited"
            except urllib.error.HTTPError as error:
                assert error.code == 429
            state.note_device_poll()
            with post("/api/emitter/main/play") as response:
                assert json.load(response)["revision"] == 1
            try:
                post("/api/emitter/main/play")
                assert False, "Public playback must be rate limited"
            except urllib.error.HTTPError as error:
                assert error.code == 429
            try:
                urllib.request.urlopen(base + "/api/emitter/main/current", timeout=2)
                assert False, "Device polling must stay private"
            except urllib.error.HTTPError as error:
                assert error.code == 401
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
