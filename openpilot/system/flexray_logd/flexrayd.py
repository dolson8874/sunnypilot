"""Publish CAN events on the dedicated FlexRay logging transport.

The channel deliberately carries Event.can, so rlogs need no custom schema.
Use raw socket subscribers (loggerd/Cabana), not SubMaster(['flexray']), which
expects channel names to match Event union members. Never publish on 'can':
pandad owns that channel.
"""
import json
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from openpilot.cereal import messaging
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.system.flexray_logd.diagnostics import DiagnosticReceiver
from openpilot.common.swaglog import cloudlog

# Match PANDA_BUS_OFFSET: pandad currently owns one Panda (sources 0–3).
FLEXRAY_SOURCE_OFFSET = 4
MAX_READ = 0x4000
CAPTURE_BINARY = Path(BASEDIR) / "openpilot/system/flexray_logd/flexray_logd"


def unpack_frames(pending: bytearray) -> list[dict]:
  frames = []
  position = 0
  while len(pending) - position >= 6:
    header = pending[position:position + 6]
    address = int.from_bytes(header[1:5], "little") >> 3
    words = header[5]
    if header[0] & 0xF1 or header[1] & 7 or address > 0x7FF or words > 127:
      raise ValueError("invalid capture envelope")
    data_size = words * 2 + 5
    if len(pending) - position < 6 + data_size:
      break
    body = pending[position + 6:position + 6 + data_size]
    if body[0] > 31 or body[1] > 63:
      raise ValueError("invalid capture metadata")
    frames.append({"address": address, "src": FLEXRAY_SOURCE_OFFSET + ((header[0] >> 1) & 7),
                   "dat": bytes(body)})
    position += 6 + data_size
  del pending[:position]
  return frames


def read_capture(path: str) -> bytes:
  data = bytearray()
  with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    client.settimeout(0.2)
    client.connect(path)
    client.sendall(b'\x80' + MAX_READ.to_bytes(2, "big"))
    while len(data) < MAX_READ:
      try:
        block = client.recv(MAX_READ - len(data))
      except TimeoutError:
        break  # Preserve any bytes already received; the next request resumes the stream.
      if not block:
        break
      data.extend(block)
  return bytes(data)


def frame_message(frames: list[dict]):
  message = messaging.new_message('can', len(frames))
  message.valid = bool(frames)
  message.can = frames
  return message


def stop_capture(process: subprocess.Popen) -> None:
  if process.poll() is None:
    process.send_signal(signal.SIGINT)
    try:
      process.wait(timeout=3.5)
    except subprocess.TimeoutExpired:
      process.kill()
      process.wait()


def run_capture(pm, socket_path: str, stop, binary: Path = CAPTURE_BINARY, capture_args: tuple[str, ...] = (), observe=None) -> None:
  pending = bytearray()
  process = subprocess.Popen([str(binary), *capture_args, '-p', socket_path])
  last_publish = 0.0
  try:
    while not stop():
      if process.poll() is not None:
        raise RuntimeError(f"capture exited with status {process.returncode}")
      try:
        data = read_capture(socket_path)
      except OSError:
        data = b''
      pending.extend(data)
      frames = unpack_frames(pending)
      if frames:
        pm.send('flexray', frame_message(frames))
        last_publish = time.monotonic()
      elif time.monotonic() - last_publish >= 1:
        pm.send('flexray', frame_message([]))
        last_publish = time.monotonic()
      if observe is not None:
        observe()
      time.sleep(0.01)
  finally:
    try:
      if process.poll() is None:
        process.send_signal(signal.SIGINT)
        deadline = time.monotonic() + 1
        while process.poll() is None and time.monotonic() < deadline:
          try:
            pending.extend(read_capture(socket_path))
            frames = unpack_frames(pending)
            if frames:
              pm.send('flexray', frame_message(frames))
          except (OSError, ValueError):
            break
          time.sleep(0.01)
    finally:
      stop_capture(process)
    if pending:
      cloudlog.warning(f"FlexRay incomplete socket tail: {len(pending)} bytes")


def main() -> None:
  stopped = False

  def request_stop(signum, frame):
    nonlocal stopped
    stopped = True

  signal.signal(signal.SIGINT, request_stop)
  signal.signal(signal.SIGTERM, request_stop)
  pm = messaging.PubMaster(['flexray'])
  receiver = None
  bus = Params().get('FlexrayDiagnosticBus', return_default=True)
  if bus in range(4):
    try:
      receiver = DiagnosticReceiver(bus)
    except Exception:
      cloudlog.exception('FlexRay diagnostic subscriber unavailable; SPI capture continues')
  elif bus != -1:
    cloudlog.error(f'Invalid FlexrayDiagnosticBus={bus}; select -1 (disabled) or 0..3')

  def observe():
    nonlocal receiver
    if receiver is not None:
      try:
        status = receiver.poll(time.monotonic())
        if status is not None:
          cloudlog.info('FPGA logging diagnostic: ' + json.dumps(status, sort_keys=True))
      except Exception:
        cloudlog.exception('FlexRay diagnostic subscriber failed; SPI capture continues')
        receiver = None

  while not stopped:
    try:
      # Each child gets its own socket, so retries never consume a different collector's data.
      with tempfile.TemporaryDirectory(prefix='flexray-') as directory:
        run_capture(pm, str(Path(directory) / 'capture.sock'), lambda: stopped, observe=observe)
    except (OSError, RuntimeError, ValueError) as error:
      cloudlog.error(f"FlexRay capture unavailable: {error}; retrying in 5 seconds")
      pm.send('flexray', frame_message([]))
      deadline = time.monotonic() + 5
      while not stopped and time.monotonic() < deadline:
        observe()
        time.sleep(0.1)


if __name__ == '__main__':
  main()
