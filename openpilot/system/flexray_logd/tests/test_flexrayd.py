import tempfile
import time
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from opendbc.car.structs import car
from openpilot.cereal import log, messaging
from openpilot.cereal.services import SERVICE_LIST
from openpilot.common.params import Params
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.common.basedir import BASEDIR
from openpilot.system.flexray_logd.flexrayd import frame_message, run_capture, unpack_frames
from openpilot.system.manager.process_config import FlexrayProcess, flexray_logging


@pytest.fixture(autouse=True)
def isolated_prefix():
  with OpenpilotPrefix():
    yield


def envelope(frame_id=0x47F, flags=3, cycle=7, payload=b'\x12\x34', crc=0x123456):
  return b'\x04' + (frame_id << 3).to_bytes(4, 'little') + bytes([len(payload) // 2, flags, cycle]) + payload + crc.to_bytes(3, 'big')


def test_default_and_toggle_conditions(tmp_path):
  params = Params(str(tmp_path))
  assert params.get_default_value('FlexrayLoggingEnabled') is True
  assert params.get_default_value('FlexrayDiagnosticBus') == -1
  params.put_bool('FlexrayLoggingEnabled', params.get_default_value('FlexrayLoggingEnabled'), block=True)
  cp = car.CarParams.new_message()
  cp.passive = True
  assert flexray_logging(True, params, cp)  # Dashcam does not suppress logging.
  assert not flexray_logging(False, params, cp)
  params.put_bool('FlexrayLoggingEnabled', False, block=True)
  assert not flexray_logging(True, params, cp)
  assert not Params(str(tmp_path)).get_bool('FlexrayLoggingEnabled')
  params.put_bool('FlexrayLoggingEnabled', True, block=True)
  assert flexray_logging(True, params, cp)


def test_all_fragment_boundaries_and_schema_roundtrip():
  payload = bytes(range(254))
  data = envelope(payload=payload)
  for split in range(len(data)):
    pending = bytearray(data[:split])
    assert unpack_frames(pending) == []
    pending.extend(data[split:])
    frames = unpack_frames(pending)
    assert pending == b''
    assert len(frames) == 1
    with log.Event.from_bytes(frame_message(frames).to_bytes()) as event:
      assert event.which() == 'can'
      assert event.valid
      frame = event.can[0]
      assert frame.address == 0x47F
      assert frame.src == 6
      assert frame.dat == bytes([3, 7]) + payload + b'\x12\x34\x56'
  assert not frame_message([]).valid
  for bus in range(8):
    pending = bytearray(envelope())
    pending[0] = bus << 1
    assert unpack_frames(pending)[0]['src'] == 4 + bus
  assert SERVICE_LIST['flexray'].should_log
  assert SERVICE_LIST['flexray'].decimation is None


def test_malformed_envelopes():
  for index, value in [(0, 0xFF), (1, 1), (5, 128), (6, 32), (7, 64)]:
    data = bytearray(envelope())
    data[index] = value
    with pytest.raises(ValueError):
      unpack_frames(data)


def test_native_capture_to_publisher(monkeypatch):
  from openpilot.system.flexray_logd.tests.test_capture import frame

  class Publisher:
    def __init__(self):
      self.frames = []

    def send(self, service, message):
      self.frames.extend(frame.to_dict() for frame in message.can)

  monkeypatch.delenv('FLEXRAY_LOG_DIR', raising=False)
  publisher = Publisher()
  with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / 'input'
    source.write_bytes((frame(2) + frame(0)) * 2048)
    deadline = time.monotonic() + 3
    run_capture(
      publisher, str(Path(directory) / 's'), lambda: len(publisher.frames) > 100 or time.monotonic() > deadline, capture_args=('-f', str(source), '-l')
    )
    assert len(publisher.frames) > 100
    assert all(f['address'] == 0x47F and f['src'] in (4, 6) and f['dat'][1] == 7 for f in publisher.frames)
    assert {f['src'] for f in publisher.frames} == {4, 6}
    assert not (Path(directory) / 's').exists()
    assert not list(Path(directory).glob('*.log'))


def test_native_capture_is_recorded_in_rlog(tmp_path, monkeypatch):
  from openpilot.system.flexray_logd.tests.test_capture import frame
  from openpilot.tools.lib.logreader import LogReader

  log_root = tmp_path / 'logs'
  monkeypatch.setenv('LOG_ROOT', str(log_root))
  monkeypatch.setenv('LOGGERD_TEST', '1')
  monkeypatch.setenv('LOGGERD_SEGMENT_LENGTH', '60')
  monkeypatch.delenv('FLEXRAY_LOG_DIR', raising=False)
  source = tmp_path / 'input'
  source.write_bytes((frame(2) + frame(0)) * 2048)
  pm = messaging.PubMaster(['flexray', 'can'])
  count = 0

  class Publisher:
    def send(self, service, message):
      nonlocal count
      count += len(message.can)
      pm.send(service, message)

  process = subprocess.Popen([str(Path(BASEDIR) / 'openpilot/system/loggerd/loggerd')], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  try:
    assert pm.wait_for_readers_to_update('flexray', timeout=5)
    assert pm.wait_for_readers_to_update('can', timeout=5)
    vehicle = messaging.new_message('can', 1)
    vehicle.can = [{'address': 0x123, 'src': 0, 'dat': b'car CAN'}]
    pm.send('can', vehicle)
    from openpilot.system.flexray_logd.tests.test_diagnostics import payload, firmware_payload

    diagnostics = messaging.new_message('can', 9)
    diagnostics.valid = True
    diagnostics.can = [{'address': 0x1FA, 'src': 1, 'dat': payload(page, 9)} for page in range(8)] + [{'address': 0x1FA, 'src': 1, 'dat': firmware_payload()}]
    pm.send('can', diagnostics)
    long_data = bytearray(envelope(payload=bytes(range(254))))
    bcm_data = bytearray(long_data)
    bcm_data[0] = 0
    long_frame = unpack_frames(long_data + bcm_data)
    pm.send('flexray', frame_message(long_frame))
    deadline = time.monotonic() + 3
    run_capture(Publisher(), str(tmp_path / 'capture.sock'), lambda: count > 100 or time.monotonic() > deadline, capture_args=('-f', str(source), '-l'))
    assert count > 100
    assert pm.wait_for_readers_to_update('flexray', timeout=5)
  finally:
    process.send_signal(signal.SIGINT)
    try:
      output, _ = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
      process.kill()
      process.communicate()
      raise
  assert process.returncode == 0, output
  files = list(log_root.glob('*/rlog.zst'))
  assert files
  recorded = [f.to_dict() for path in files for event in LogReader(str(path)) if event.which() == 'can' for f in event.can]
  captured = [f for f in recorded if f['src'] in (4, 6)]
  assert len(captured) == count + 2
  assert {f['src'] for f in captured} == {4, 6}
  assert all(f['address'] == 0x47F for f in captured)
  assert sum(f['dat'] == b'\x03\x07' + bytes(range(254)) + b'\x12\x34\x56' for f in captured) == 2
  assert all(f['dat'][:6] == b'\x03\x07\x12\x34\x56\x78' for f in captured if len(f['dat']) != 259)
  assert any(f['src'] == 0 and f['address'] == 0x123 and f['dat'] == b'car CAN' for f in recorded)
  from openpilot.system.flexray_logd.diagnostics import DiagnosticAssembler

  assembler = DiagnosticAssembler(1)
  diagnostic_frames = [f for f in recorded if f['address'] == 0x1FA]
  assert len(diagnostic_frames) == 9
  for index, diagnostic in enumerate(diagnostic_frames):
    assert diagnostic['src'] == 1
    assert diagnostic['dat'] == (payload(index, 9) if index < 8 else firmware_payload())
    assembler.accept(diagnostic['address'], diagnostic['src'], diagnostic['dat'], index * 0.01)
  assert assembler.last_complete.sequence == 9
  assert assembler.status(0.1)['firmware']['description'] == 'FPGA firmware 1.0.0 / build 1'
  for path in log_root.glob('*/qlog.zst'):
    assert all(f.src not in (4, 6) for event in LogReader(str(path)) if event.which() == 'can' for f in event.can)


def test_manager_restarts_only_exited_publisher(monkeypatch):
  from openpilot.system.manager.process import PythonProcess

  process = FlexrayProcess('flexray_logd', 'unused', lambda *args: True)
  stopped = []
  started = []

  def stop():
    stopped.append(process.proc)
    process.proc = None

  monkeypatch.setattr(process, 'stop', stop)
  monkeypatch.setattr(PythonProcess, 'start', lambda self: started.append(self.proc))
  process.proc = SimpleNamespace(exitcode=None)
  process.start()
  assert not stopped
  assert started[-1] is process.proc
  process.proc = SimpleNamespace(exitcode=1)
  process.start()
  assert len(stopped) == 1
  assert started[-1] is None


@pytest.mark.parametrize('failure', ['startup', 'poll'])
def test_diagnostic_failure_does_not_stop_spi_publisher(monkeypatch, failure):
  from openpilot.system.flexray_logd import flexrayd

  handlers = {}
  captures = []

  class BrokenReceiver:
    def __init__(self, bus):
      assert bus == 1
      if failure == 'startup':
        raise OSError('diagnostic CAN socket unavailable')

    def poll(self, now):
      raise RuntimeError('diagnostic observer failed')

  def capture(pm, path, stop, **kwargs):
    kwargs['observe']()
    captures.append(not stop())
    handlers[signal.SIGTERM](signal.SIGTERM, None)

  monkeypatch.setattr(flexrayd, 'Params', lambda: SimpleNamespace(get=lambda *args, **kwargs: 1))
  monkeypatch.setattr(flexrayd, 'DiagnosticReceiver', BrokenReceiver)
  monkeypatch.setattr(flexrayd.messaging, 'PubMaster', lambda services: object())
  monkeypatch.setattr(flexrayd.signal, 'signal', lambda sig, handler: handlers.__setitem__(sig, handler))
  monkeypatch.setattr(flexrayd, 'run_capture', capture)
  flexrayd.main()
  assert captures == [True]
