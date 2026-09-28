from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

import debug_host


def test_debug_host_serves_voice_and_classic_pages_without_path_escape(tmp_path, monkeypatch):
    debug = tmp_path / 'debug'
    voice = tmp_path / 'voice'
    for folder, label in ((debug, 'classic'), (voice, 'studio')):
        (folder / 'assets').mkdir(parents=True)
        (folder / 'index.html').write_text(label)
        (folder / 'assets' / 'app.js').write_text(label + '-script')
    (tmp_path / 'private.txt').write_text('not served')
    monkeypatch.setattr(debug_host, 'DEBUG_APP_DIR', debug)
    monkeypatch.setattr(debug_host, 'DEBUG_APP', debug / 'index.html')
    monkeypatch.setattr(debug_host, 'VOICE_APP_DIR', voice)
    server = ThreadingHTTPServer(('127.0.0.1', 0), debug_host.make_handler('http://127.0.0.1:1'))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        for path, expected in (('/', 'classic'), ('/debug/', 'classic'), ('/debug/assets/app.js', 'classic-script'),
                               ('/assets/app.js', 'classic-script'), ('/voice/', 'studio'), ('/voice/assets/app.js', 'studio-script')):
            with urlopen(base + path) as response:
                assert response.read().decode() == expected
        for path in ('/voice/../private.txt', '/voice/../debug/index.html', '/../private.txt'):
            with pytest.raises(HTTPError) as error:
                urlopen(base + path)
            assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
