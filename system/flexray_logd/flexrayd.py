"""Publish CAN events on the dedicated FlexRay logging transport.

The data channel deliberately carries Event.can, preserving the frame schema.
Capture health is published separately on flexrayStatus.
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

from cereal import messaging
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.system.flexray_logd.diagnostics import DiagnosticReceiver
from openpilot.common.swaglog import cloudlog
from openpilot.system.flexray_logd.native_capture import NativeCaptureLog
from openpilot.system.flexray_logd.status import CaptureStatus
from openpilot.system.flexray_logd.startup import LoggerStartup
from openpilot.system.flexray_logd.usb_inventory import start_usb_inventory

# Match PANDA_BUS_OFFSET: pandad currently owns one Panda (sources 0–3).
FLEXRAY_SOURCE_OFFSET = 4
MAX_READ = 0x4000
CAPTURE_BINARY = Path(BASEDIR) / "system/flexray_logd/flexray_logd"


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


def run_capture(pm, socket_path: str, stop, binary: Path = CAPTURE_BINARY, capture_args: tuple[str, ...] = (),
                observe=None, telemetry=None, startup=None) -> None:
  pending = bytearray()
  process = subprocess.Popen([str(binary), *capture_args, '-p', socket_path], stderr=subprocess.PIPE)
  native = NativeCaptureLog(process)
  if telemetry is not None:
    telemetry.starting(process.pid)
  state = {'state': 'starting', 'pid': process.pid, 'last_valid_frame_monotonic': None}
  cloudlog.info('FlexRay capture state: ' + json.dumps(state))
  last_state = 0.0
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
        state['last_valid_frame_monotonic'] = time.monotonic()
        if startup is not None:
          startup.submit(frames)
        else:
          pm.send('flexray', frame_message(frames))
          if telemetry is not None:
            telemetry.received(frames)
        last_publish = time.monotonic()
      elif time.monotonic() - last_publish >= 1 and (startup is None or startup.ready):
        pm.send('flexray', frame_message([]))
        last_publish = time.monotonic()
      native.report()
      if startup is not None:
        startup.poll()
      if telemetry is not None:
        telemetry.native(native.health())
        telemetry.publish()
      now = time.monotonic()
      if now - last_state >= 1:
        health = native.health()
        state.update(health)
        activity = [value for value in (health['last_successful_read_monotonic'], state['last_valid_frame_monotonic']) if value is not None]
        state['last_valid_frame_age_s'] = None if state['last_valid_frame_monotonic'] is None else now - state['last_valid_frame_monotonic']
        state['state'] = ('running-with-data' if now - max(activity) < 3 else 'waiting-for-data') if activity else 'starting'
        cloudlog.info('FlexRay capture state: ' + json.dumps(state))
        last_state = now
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
              if startup is not None:
                startup.submit(frames)
                startup.poll()
              else:
                pm.send('flexray', frame_message(frames))
                if telemetry is not None:
                  telemetry.received(frames)
          except (OSError, ValueError):
            break
          time.sleep(0.01)
    finally:
      stop_capture(process)
      native.finish()
      if telemetry is not None:
        telemetry.native(native.health())
      state.update(native.health())
      state.update(state='stopped' if stop() else 'retrying', returncode=process.returncode)
      cloudlog.info('FlexRay capture state: ' + json.dumps(state))
    if pending:
      cloudlog.warning(f"FlexRay incomplete socket tail: {len(pending)} bytes")


def main() -> None:
  stopped = False

  def request_stop(signum, frame):
    nonlocal stopped
    stopped = True

  signal.signal(signal.SIGINT, request_stop)
  signal.signal(signal.SIGTERM, request_stop)
  pm = messaging.PubMaster(['flexray', 'flexrayStatus'])
  telemetry = CaptureStatus(pm)
  startup = LoggerStartup(pm, Params(), telemetry)
  startup.poll()
  inventory = start_usb_inventory()
  receiver = None
  bus = Params().get('FlexrayDiagnosticBus', return_default=True)
  if bus in range(4):
    try:
      receiver = DiagnosticReceiver(bus)
    except Exception:
      cloudlog.exception('FlexRay diagnostic subscriber unavailable; SPI capture continues')
  elif bus == -1:
    cloudlog.info('FlexrayDiagnosticBus=-1: FPGA CAN diagnostics disabled; observed vehicle uses bus 1, configure explicitly')
  elif bus != -1:
    cloudlog.error(f'Invalid FlexrayDiagnosticBus={bus}; select -1 (disabled) or 0..3')

  def observe():
    nonlocal receiver
    startup.poll()
    telemetry.publish()
    if inventory is not None:
      inventory.report()
    if receiver is not None:
      try:
        status = receiver.poll(time.monotonic())
        if status is not None:
          cloudlog.info('FPGA logging diagnostic: ' + json.dumps(status, sort_keys=True))
      except Exception:
        cloudlog.exception('FlexRay diagnostic subscriber failed; SPI capture continues')
        receiver = None

  try:
    retries = 0
    while not stopped:
      try:
        # Each child gets its own socket, so retries never consume a different collector's data.
        with tempfile.TemporaryDirectory(prefix='flexray-') as directory:
          run_capture(pm, str(Path(directory) / 'capture.sock'), lambda: stopped, observe=observe, telemetry=telemetry, startup=startup)
      except (OSError, RuntimeError, ValueError) as error:
        retries += 1
        telemetry.retrying(error)
        cloudlog.error(f"FlexRay capture state=retrying retry_count={retries} last_actual_error={error}; retrying in 5 seconds")
        pm.send('flexray', frame_message([]))
        deadline = time.monotonic() + 5
        while not stopped and time.monotonic() < deadline:
          observe()
          time.sleep(0.1)

  finally:
    try:
      if inventory is not None:
        inventory.report()
    finally:
      startup.close()
      telemetry.phase = 'stopped'
      try:
        telemetry.publish(force=True)
      except Exception:
        cloudlog.exception('FlexRay final status publication failed')


if __name__ == '__main__':
  main()
