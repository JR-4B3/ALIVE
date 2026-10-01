"""Temporary serial speaker API. Run beside the serial_message prototype firmware.
The contact field sets literal test text. This bridge does not call the reply model.
"""
import json
import threading
import os
import subprocess
from urllib.parse import urlparse, parse_qs
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import serial

sounds = ['original', 'drift', 'beacon', 'chorus']
message = 'HELLO'
ready_at = 0.0
lock = threading.Lock()
device = serial.Serial('/dev/ttyACM0', 115200, timeout=.1)
time.sleep(1)
device.read_all()
# Real capture from main, held only in a short memory buffer.
capture = subprocess.Popen(['parecord', '--device=alsa_input.usb-Focusrite_Scarlett_Solo_USB_Y75R5QV1502398-00.pro-input-0', '--rate=48000', '--channels=1', '--format=s16le', '--raw'], stdout=subprocess.PIPE, env={**os.environ, 'XDG_RUNTIME_DIR': '/run/user/1000'})
audio_lock = threading.Lock()
audio = bytearray()
cursor = 0

def read_audio():
    global cursor
    while chunk := capture.stdout.read(4096):
        with audio_lock:
            audio.extend(chunk)
            cursor += len(chunk)
            if len(audio) > 48000 * 2 * 5: del audio[:-48000 * 2 * 5]
threading.Thread(target=read_audio, daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != '/api/prototype/microphone': return self.respond({'error': 'Unknown endpoint'}, 404)
        after = int(parse_qs(parsed.query).get('after', ['0'])[0])
        with audio_lock:
            length = min(len(audio), max(0, cursor - after), 48000 * 2)
            data = bytes(audio[-length:]) if length else b''
            current = cursor
        self.send_response(200)
        self.send_header('content-type', 'application/octet-stream')
        self.send_header('content-length', str(len(data)))
        self.send_header('x-audio-cursor', str(current))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        global message, ready_at
        payload = json.loads(self.rfile.read(int(self.headers.get('content-length', 0))) or '{}')
        with lock:
            if self.path == '/api/message':
                message = ''.join(c for c in str(payload.get('message', '')).upper() if c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ ')[:12].strip() or 'HELLO'
                return self.respond({'reply': message, 'message': message})
            if self.path == '/api/emitter/main/play':
                if time.monotonic() < ready_at:
                    return self.respond({'error': f'Wait {int(ready_at-time.monotonic())+1}s before replaying'}, 429)
                sound = payload.get('soundDirection', 'original')
                if sound not in sounds: return self.respond({'error': 'Unknown sound direction'}, 400)
                duration = .25 + 1 + sum(.22 + max(220, round((1600 if c == ' ' else 100 + (ord(c)-65)*50)*.65))/1000 for c in message)
                if sound != 'original': duration += 3.95
                device.read_all()
                device.write(f'PLAY {message}|{sounds.index(sound)}\n'.encode())
                ready_at = time.monotonic() + duration + 1
                return self.respond({'message': message, 'duration': duration, 'soundDirection': sound})
            self.respond({'error': 'Unknown prototype endpoint'}, 404)
    def respond(self, payload, status=200):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def log_message(self, *args): pass

print('Prototype serial speaker API on 127.0.0.1:8766', flush=True)
try:
    ThreadingHTTPServer(('127.0.0.1', 8766), Handler).serve_forever()
finally:
    capture.terminate()
    device.close()
