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
        state.device_command()
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
    state.device_command()
    assert state.play_current_once()["revision"] == 1
    restored = ApiState("HELLO", state_file=file)
    assert restored.current_emitter_message()["message"] == "I AM HERE"
    assert restored.current_emitter_message()["revision"] == 1
    restored.device_command()
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
            state.device_command()
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


def test_playing_board_stays_online_for_the_longest_message():
    # A 12-letter reply plays for about 14 s, during which the board does not poll.
    state = ApiState("ZZZZZZZZZZZZ")
    with patch("emitter.time.monotonic", return_value=1000):
        state.device_command()
    with patch("emitter.time.monotonic", return_value=1015):
        assert state.current_emitter_message()["deviceOnline"] is True
        assert state.play_current_once()["revision"] == 1
    with patch("emitter.time.monotonic", return_value=1031):
        assert state.current_emitter_message()["deviceOnline"] is False


def test_preparing_a_reply_does_not_change_a_queued_command():
    state = ApiState("HELLO")
    state.device_command()
    state.play_current_once()
    state.set_reply("HI")
    assert state.device_command() == {"revision": 1, "message": "HELLO", "soundDirection": "original"}
    state.play_current_once()
    assert state.device_command() == {"revision": 2, "message": "HI", "soundDirection": "original"}


def test_failed_save_publishes_nothing(tmp_path):
    state = ApiState("HELLO", state_file=tmp_path / "state.json")
    state.device_command()
    with patch("emitter.os.replace", side_effect=OSError("disk full")):
        for action in (state.play_current_once, lambda: state.set_reply("HI")):
            try:
                action()
                assert False, "the save error must reach the caller"
            except OSError:
                pass
    assert state.device_command() == {"revision": 0, "message": "HELLO", "soundDirection": "original"}
    assert state.current_emitter_message()["message"] == "HELLO"


def test_unreadable_state_is_kept_aside_and_startup_continues(tmp_path):
    file = tmp_path / "state.json"
    file.write_text("{not json", encoding="utf-8")
    state = ApiState("HELLO", state_file=file)
    assert state.device_command() == {"revision": 0, "message": "HELLO", "soundDirection": "original"}
    kept = list(tmp_path.glob("state.json.invalid-*"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == "{not json"


def test_health_endpoint_needs_no_token():
    state = ApiState("HELLO")
    with patch.dict("os.environ", {"ALIVE_WEB_TOKEN": "web-secret"}):
        server = QuietThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/healthz",
                                        timeout=2) as response:
                assert json.load(response) == {"status": "ok"}
        finally:
            server.shutdown()
            server.server_close()


def test_board_polls_are_logged_per_day_and_old_days_pruned(tmp_path):
    state = ApiState("HELLO", state_file=tmp_path / "state.json")
    folder = tmp_path / "device-polls"
    folder.mkdir()
    (folder / "2026-09-01.csv").write_text("old\n")
    (folder / "2026-09-25.csv").write_text("recent\n")
    with patch("emitter.time.time", return_value=1_791_115_200):  # 2026-10-04T12:00:00Z
        state.device_command("70:AF:09:0D:AB:24", "123456", "9")
        state.device_command("70:AF:09:0D:AB:24", "not-a-number", "1")
        state.device_command("70:AF:09:0D:AB:24,x", "1", "1")
        state.device_command()
    assert (folder / "2026-10-04.csv").read_text() == (
        "received_utc,board,uptime_ms,reset_reason\n"
        "2026-10-04T12:00:00Z,70:AF:09:0D:AB:24,123456,9\n")
    assert sorted(path.name for path in folder.iterdir()) == ["2026-09-25.csv", "2026-10-04.csv"]
    assert state.current_emitter_message()["deviceOnline"] is True


def test_device_poll_headers_reach_the_log_and_health_checks_do_not(tmp_path):
    state = ApiState("HELLO", state_file=tmp_path / "state.json")
    with patch.dict("os.environ", {"ALIVE_DEVICE_TOKEN": "device-secret"}):
        server = QuietThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            urllib.request.urlopen(base + "/healthz", timeout=2).close()
            urllib.request.urlopen(urllib.request.Request(base + "/api/emitter/main/current", headers={
                "Authorization": "Bearer device-secret", "X-Alive-Board": "AC:27:6E:45:B9:4C",
                "X-Alive-Uptime-Ms": "2000", "X-Alive-Reset": "1"}), timeout=2).close()
        finally:
            server.shutdown()
            server.server_close()
    rows = next((tmp_path / "device-polls").glob("*.csv")).read_text().splitlines()
    assert len(rows) == 2 and rows[1].endswith(",AC:27:6E:45:B9:4C,2000,1")
