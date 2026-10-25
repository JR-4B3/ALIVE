import json
import random
import threading
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

import emitter
from emitter import ApiState, QuietThreadingHTTPServer, make_handler
from reply_engine import signal_duration_seconds
from signals import message_score, noise_score, score_seconds

BOARDS = ["70:AF:09:0D:D7:BC", "AC:27:6E:45:B9:4C", "AC:27:6E:45:E5:90", "70:AF:09:0D:AB:24", "AC:27:6E:45:00:01"]


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    value = Clock()
    with patch("emitter.time.monotonic", value):
        yield value


def poll(state, board):
    return state.device_command(board, "5000", "3")


def poll_all(state, boards=BOARDS):
    return {board: poll(state, board) for board in boards}


def run(state, clock, seconds, boards=BOARDS, step=2.0):
    """Poll like the firmware: every 2 s, and not while a board plays."""
    played = []
    busy_until = {board: 0.0 for board in boards}
    end = clock.now + seconds
    while clock.now < end:
        for board in boards:
            if clock.now >= busy_until[board]:
                play = poll(state, board)["play"]
                if play:
                    played.append((clock.now, board, play))
                    busy_until[board] = clock.now + score_seconds(play)
        clock.now += step
    return played


def test_message_score_matches_the_reply_duration():
    for text in ["HI", "WE ARE HERE", "Z" * 40]:
        score = message_score(text)
        assert score_seconds(score) == signal_duration_seconds(text)
        assert len(score["chirps"]) == len(text) + 3


def test_noise_chirps_stay_apart_so_a_phone_hears_each_one():
    rng = random.Random(4)
    for _ in range(100):
        assert all(gap >= 180 and 0 <= symbol < 27 for symbol, gap in noise_score(rng)["chirps"])


def test_only_one_board_is_ever_on_the_air(clock):
    state = ApiState(rng=random.Random(7))
    played = run(state, clock, 1800)
    assert len(played) > 40
    for (start, _, play), (next_start, _, _) in zip(played, played[1:]):
        assert next_start >= start + score_seconds(play) + emitter.AIR_GAP_SECONDS
    kinds = {play["kind"] for _, _, play in played}
    assert kinds == {"noise", "clock", "intelligent"}
    assert played[0][2]["kind"] == "intelligent"


def test_five_boards_get_one_intelligent_role_and_at_most_one_dead(clock):
    for seed in range(30):
        state = ApiState(rng=random.Random(seed))
        poll_all(state)
        roles = [poll(state, board)["role"] for board in BOARDS]
        assert roles.count("intelligent") == 1
        assert roles.count("dead") <= 1
        assert {"clock", "noise"} <= set(roles)


def test_each_kind_plays_from_a_board_with_that_role(clock):
    state = ApiState(rng=random.Random(3))
    poll_all(state)
    played = run(state, clock, 500)
    roles = {board: poll(state, board)["role"] for board in BOARDS}
    for _, board, play in played:
        assert roles[board] == play["kind"]


def test_a_single_board_plays_every_kind(clock):
    state = ApiState(rng=random.Random(5))
    played = run(state, clock, 900, boards=BOARDS[:1])
    assert {play["kind"] for _, _, play in played} == {"noise", "clock", "intelligent"}


def test_roles_change_over_time_but_not_during_a_conversation(clock):
    state = ApiState(rng=random.Random(11))
    roles = lambda: {board: poll(state, board)["role"] for board in BOARDS}
    poll_all(state)
    first = roles()
    run(state, clock, emitter.ROLE_SECONDS - 10)
    assert roles() == first
    state.queue_reply("visitor-0001", "hello", "WE ARE HERE")
    run(state, clock, emitter.CONVERSATION_HOLD_SECONDS - 10)
    assert roles() == first
    deals = []
    for _ in range(4):
        run(state, clock, emitter.ROLE_SECONDS)
        deals.append(roles())
    assert any(deal != first for deal in deals)


def test_the_intelligent_role_moves_when_its_board_goes_quiet(clock):
    state = ApiState(rng=random.Random(2))
    poll_all(state)
    intelligent = next(board for board in BOARDS if poll(state, board)["role"] == "intelligent")
    others = [board for board in BOARDS if board != intelligent]
    run(state, clock, emitter.DEVICE_LEASE_SECONDS + 4, boards=others)
    roles = [poll(state, board)["role"] for board in others]
    assert roles.count("intelligent") == 1


def test_a_reply_waits_for_the_air_and_goes_to_the_intelligent_board(clock):
    state = ApiState(rng=random.Random(8))
    played = run(state, clock, 4)
    assert played and played[0][2]["kind"] == "intelligent"
    state.queue_reply("visitor-0001", "who are you", "WE ARE LANTERN")
    responses = poll_all(state)
    assert all(response["play"] is None for response in responses.values())
    played = run(state, clock, 30)
    assert played[0][2]["text"] == "WE ARE LANTERN"
    assert poll(state, played[0][1])["role"] == "intelligent"


def test_old_replies_expire_when_no_board_plays_them(clock):
    state = ApiState(rng=random.Random(1))
    poll(state, BOARDS[0])
    state.queue_reply("", "hi", "OLD")
    clock.now += emitter.REPLY_EXPIRY_SECONDS + 1
    played = run(state, clock, 60, boards=BOARDS[:1])
    assert all(play.get("text") != "OLD" for _, _, play in played)


def test_contact_needs_a_decoded_transmission(clock):
    state = ApiState(rng=random.Random(8))
    assert not state.has_contact("visitor-0001", "IS ANYONE THERE")
    played = run(state, clock, 4)
    text = played[0][2]["text"]
    assert not state.has_contact("visitor-0001", "")
    assert not state.has_contact("visitor-0001", "QQQQQQQQQ")
    # A phone may miss or confuse a letter.
    assert state.has_contact("visitor-0001", text[:-1] + "Q")
    assert state.has_contact("visitor-0001", "")
    assert not state.has_contact("visitor-0002", "")
    clock.now += emitter.CONTACT_SECONDS + 1
    assert not state.has_contact("visitor-0001", "")


def test_conversation_history_is_per_visitor_and_bounded(clock):
    state = ApiState()
    for turn in range(10):
        state.queue_reply("visitor-0001", f"question {turn}", "ANSWER")
    state.queue_reply("visitor-0002", "hello", "HI")
    history = state.conversation("visitor-0001")
    assert len(history) == emitter.CONVERSATION_TURNS and history[-1] == ("question 9", "ANSWER")
    assert state.conversation("visitor-0002") == [("hello", "HI")]


def test_playing_board_stays_online_for_the_longest_reply(clock):
    state = ApiState()
    poll(state, BOARDS[0])
    clock.now += signal_duration_seconds("Z" * 40) + 2
    assert state.status()["deviceOnline"] is True


def serve(state, environment):
    patcher = patch.dict("os.environ", environment)
    patcher.start()
    server = QuietThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def stop():
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        patcher.stop()

    return f"http://127.0.0.1:{server.server_port}", stop


def request(base, path, token=None, origin=None, method="GET", payload=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if origin:
        headers["Origin"] = origin
    data = json.dumps(payload).encode() if payload is not None else None
    return urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers,
                                                         method=method), timeout=2)


def http_error(call):
    try:
        call().close()
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)
    raise AssertionError("expected an HTTP error")


def test_web_and_device_use_separate_tokens_and_restricted_origin():
    state = ApiState(rng=random.Random(8))
    base, stop = serve(state, {"ALIVE_WEB_TOKEN": "web-secret", "ALIVE_DEVICE_TOKEN": "device-secret",
                               "ALIVE_WEB_ORIGIN": "https://site.example"})
    try:
        code, body = http_error(lambda: request(base, "/api/emitter/main/play", "web-secret", method="POST"))
        assert code == 503 and body["error"].startswith("No unit is polling")
        with request(base, "/api/emitter/main/current", "device-secret") as response:
            assert json.load(response)["role"] == "dead"
        assert http_error(lambda: request(base, "/api/emitter/main/current", "web-secret"))[0] == 401
        poll_headers = {"X-Alive-Board": BOARDS[0], "X-Alive-Uptime-Ms": "1", "X-Alive-Reset": "1",
                        "Authorization": "Bearer device-secret"}
        with urllib.request.urlopen(urllib.request.Request(base + "/api/emitter/main/current",
                                                           headers=poll_headers), timeout=2) as response:
            assert json.load(response)["play"]["kind"] == "intelligent"
        with request(base, "/api/emitter/main/play", "web-secret", "https://site.example", "POST",
                     {"message": "test signal"}) as response:
            assert json.load(response)["queuedReplies"] == 1
            assert response.headers["Access-Control-Allow-Origin"] == "https://site.example"
        with request(base, "/api/status", "web-secret") as response:
            assert json.load(response)["boards"][0]["role"] == "intelligent"
        with request(base, "/api/emitter/main/reset", "web-secret", method="POST") as response:
            assert json.load(response)["queuedReplies"] == 0
        assert http_error(lambda: request(base, "/api/emitter/main/reset", "device-secret", method="POST"))[0] == 401
        assert http_error(lambda: request(base, "/api/emitter/main/play", "device-secret", method="POST"))[0] == 401
        with request(base, "/api/emitter/main/play", "web-secret", "https://other.example", "POST") as response:
            assert "Access-Control-Allow-Origin" not in response.headers
    finally:
        stop()


def test_public_visitor_reaches_the_model_only_after_hearing_a_signal(clock):
    state = ApiState(rng=random.Random(8))
    environment = {"ALIVE_WEB_TOKEN": "operator-secret", "ALIVE_DEVICE_TOKEN": "device-secret",
                   "ALIVE_WEB_ORIGIN": "https://site.example", "ALIVE_PUBLIC_DEMO": "1"}
    base, stop = serve(state, environment)
    replies = []

    def fake_reply(text, history):
        replies.append((text, history))
        return "WE ARE LANTERN"

    try:
        with patch("emitter.generate_reply", fake_reply):
            visitor = {"session": "visitor-0001", "message": "Are you there?"}
            with request(base, "/api/message", origin="https://site.example", method="POST",
                         payload=visitor) as response:
                assert json.load(response) == {"contact": False}
            assert replies == []
            heard = run(state, clock, 4)[0][2]["text"]
            code, body = http_error(lambda: request(base, "/api/message", method="POST",
                                                    payload={**visitor, "heard": heard}))
            assert code == 429 and body["error"].startswith("Wait")
            clock.now += emitter.SESSION_MESSAGE_SECONDS
            with request(base, "/api/message", method="POST", payload={**visitor, "heard": heard}) as response:
                # Visitors must decode the reply; the response does not reveal it.
                assert json.load(response) == {"contact": True, "queued": 1}
            assert replies == [("Are you there?", [])]
            clock.now += emitter.SESSION_MESSAGE_SECONDS
            with request(base, "/api/message", method="POST",
                         payload={"session": "visitor-0001", "message": "Who?"}) as response:
                assert json.load(response)["contact"] is True
            assert replies[-1] == ("Who?", [("Are you there?", "WE ARE LANTERN")])
            assert http_error(lambda: request(base, "/api/emitter/main/play", method="POST"))[0] == 401
            assert http_error(lambda: request(base, "/api/emitter/main/current"))[0] == 401
    finally:
        stop()


def test_full_queue_and_offline_boards_refuse_replies(clock):
    state = ApiState()
    assert state.reply_unavailable().startswith("No unit")
    poll(state, BOARDS[0])
    for _ in range(emitter.REPLY_QUEUE_LIMIT):
        state.queue_reply("", "hi", "HELLO")
    assert state.reply_unavailable().startswith("The channel is busy")


def test_health_endpoint_needs_no_token():
    state = ApiState()
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
    state = ApiState(state_file=tmp_path / "state.json")
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
    assert state.status()["deviceOnline"] is True


def test_device_poll_headers_reach_the_log_and_health_checks_do_not(tmp_path):
    state = ApiState(state_file=tmp_path / "state.json")
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


def test_quiet_board_alerts_separate_dead_batteries_from_wifi_outages():
    state = ApiState()
    with patch("emitter.time.monotonic", return_value=1000):
        state.device_command("AC:27:6E:45:E5:90", "10000", "1")
        state.device_command("70:AF:09:0D:AB:24", "10000", "3")
    with patch("emitter.time.monotonic", return_value=1290):
        state.device_command("70:AF:09:0D:AB:24", "300000", "3")
    with patch("emitter.time.monotonic", return_value=1310):
        assert state.quiet_board_alerts() == [
            "ALIVE board AC:27:6E:45:E5:90 stopped polling; its battery is probably empty. "
            "It ran 0 h 00 min since power-on."]
        assert state.quiet_board_alerts() == []
    with patch("emitter.time.monotonic", return_value=1600):
        assert state.quiet_board_alerts() == [
            "ALIVE: no board has polled for 5 minutes. Check the Wi-Fi and the API before the batteries."]
        assert state.quiet_board_alerts() == []
    with patch("emitter.time.monotonic", return_value=1650):
        state.device_command("70:AF:09:0D:AB:24", "5000", "3")
        assert state.quiet_board_alerts() == ["ALIVE boards are polling again."]
        state.device_command("AC:27:6E:45:E5:90", "5000", "1")
        assert state.quiet_board_alerts() == ["ALIVE board AC:27:6E:45:E5:90 is polling again."]


def test_a_board_that_died_during_a_wifi_outage_still_gets_its_alert():
    state = ApiState()
    with patch("emitter.time.monotonic", return_value=1000):
        state.device_command("AC:27:6E:45:E5:90", "10000", "1")
        state.device_command("70:AF:09:0D:AB:24", "10000", "1")
    with patch("emitter.time.monotonic", return_value=1400):
        assert len(state.quiet_board_alerts()) == 1
    with patch("emitter.time.monotonic", return_value=1500):
        state.device_command("70:AF:09:0D:AB:24", "5000", "3")
        assert state.quiet_board_alerts() == [
            "ALIVE boards are polling again.",
            "ALIVE board AC:27:6E:45:E5:90 stopped polling; its battery is probably empty. "
            "It ran 0 h 00 min since power-on."]
