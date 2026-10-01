"""Throwaway speaker check. Requires pyserial and parecord on the hardware host."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import serial
from serial.tools import list_ports

parser = argparse.ArgumentParser()
parser.add_argument('--direction', choices=['original', 'beacon'], required=True)
parser.add_argument('--message', default='HELLO')
parser.add_argument('--port')
parser.add_argument('--source', default='alsa_input.usb-Focusrite_Scarlett_Solo_USB_Y75R5QV1502398-00.pro-input-0')
parser.add_argument('--output', default='/tmp/alive-space-prototype/captures')
args = parser.parse_args()
message = ''.join(c for c in args.message.upper() if c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ ')[:12].strip()
filename = message.replace(' ', '_')
ports = [port.device for port in list_ports.comports() if port.vid == 0x303A and port.pid == 0x1001]
port = args.port or (ports[0] if len(ports) == 1 else None)
if port is None: parser.error('Connect one ESP32 speaker or specify --port')
output = Path(args.output)
output.mkdir(parents=True, exist_ok=True)
env = {**os.environ, 'XDG_RUNTIME_DIR': '/run/user/1000'}
with serial.Serial(port, 115200, timeout=.1) as device:
    time.sleep(1)
    print(device.read_all().decode(errors='replace'), flush=True)
    for direction, name in [(0, 'original'), (2, 'beacon')]:
        if args.direction != name: continue
        recording = subprocess.Popen(['parecord', '--device', args.source, '--rate=48000', '--channels=1', '--format=s16le', '--file-format=wav', str(output / f'{name}-{filename}.wav')], env=env)
        time.sleep(.5)
        device.write(f'PLAY {message}|{direction}\n'.encode())
        started = time.monotonic()
        transcript = ''
        while time.monotonic() - started < 22:
            line = device.readline().decode(errors='replace')
            transcript += line
            if 'DONE' in line:
                time.sleep(.5)
                break
        recording.send_signal(signal.SIGINT)
        recording.wait(timeout=5)
        result = {'direction': name, 'expected': message, 'seconds': round(time.monotonic()-started, 3), 'serial': transcript}
        (output / f'{name}.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
        time.sleep(.5)
