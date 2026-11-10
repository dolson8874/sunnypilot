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
  assert params.get_default_value('FlexrayShowStatus') is True
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
  pm = messaging.PubMaster(['flexray', 'can', 'flexrayStatus'])
  from openpilot.system.flexray_logd.status import CaptureStatus
  telemetry = CaptureStatus(pm)
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
    run_capture(Publisher(), str(tmp_path / 'capture.sock'), lambda: count > 100 or time.monotonic() > deadline,
                capture_args=('-f', str(source), '-l'), telemetry=telemetry)
    telemetry.publish(force=True)
    assert pm.wait_for_readers_to_update('flexrayStatus', timeout=5)
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
  statuses = [event.flexrayStatus.to_dict() for path in files for event in LogReader(str(path)) if event.which() == 'flexrayStatus']
  assert any(status['lastFrameMonoTime'] > 0 and status['src4Frames'] > 0 and status['src6Frames'] > 0 for status in statuses)
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
  monkeypatch.setattr(flexrayd, 'start_usb_inventory', lambda: None)
  monkeypatch.setattr(flexrayd.messaging, 'PubMaster', lambda services: SimpleNamespace(send=lambda *args: None))
  monkeypatch.setattr(flexrayd.signal, 'signal', lambda sig, handler: handlers.__setitem__(sig, handler))
  monkeypatch.setattr(flexrayd, 'run_capture', capture)
  flexrayd.main()
  assert captures == [True]


def test_native_stderr_exit_and_flood(tmp_path, monkeypatch):
  import json
  import sys
  from openpilot.system.flexray_logd import flexrayd

  messages = []
  monkeypatch.setattr(flexrayd.cloudlog, 'info', messages.append)
  script = tmp_path / 'child.py'
  script.write_text("import os\nos.write(2,b'native stage=usb_claim failed rc=-5 errno=16 libusb=BUSY\\n')\n"
                    + "for i in range(2048): os.write(2,b'x'*4096)\n"
                    + "os.write(2,b'\\nnative stage=usb_open_claim failed final-cause\\n')\nraise SystemExit(1)\n")
  deadline = time.monotonic() + 5
  pm = SimpleNamespace(send=lambda *args: None)
  with pytest.raises(RuntimeError, match='status 1'):
    run_capture(pm, str(tmp_path / 'missing.sock'), lambda: time.monotonic() > deadline,
                binary=Path(sys.executable), capture_args=(str(script),))
  native = [json.loads(line.removeprefix('FlexRay native: ')) for line in messages if line.startswith('FlexRay native: ')]
  final = native[-1]
  assert final['stderr_eof'] and final['returncode'] == 1
  assert 'usb_claim' in final['first_error'] and 'final-cause' in final['last_error']
  assert final['suppressed_lines'] > 0
  assert len(final['stderr']) <= 16 and max(map(len, final['stderr_tail'])) <= 1024
  assert time.monotonic() < deadline


def test_native_immediate_stderr_exit(tmp_path, monkeypatch):
  import sys
  from openpilot.system.flexray_logd import flexrayd

  messages = []
  monkeypatch.setattr(flexrayd.cloudlog, 'info', messages.append)
  child = tmp_path / 'exit.py'
  child.write_text("import sys\nsys.stderr.write('native stage=kernel_driver_detach interface=1 rc=-5 (not cable disconnect)\\n')\n"
                   + "sys.stderr.write('native stage=gpio_setmode failed rc=-6 errno=0 final-without-newline')\nsys.exit(1)")
  with pytest.raises(RuntimeError, match='status 1'):
    run_capture(SimpleNamespace(send=lambda *args: None), str(tmp_path / 'missing.sock'), lambda: False,
                binary=Path(sys.executable), capture_args=(str(child),))
  assert any('final-without-newline' in message and '"stderr_eof": true' in message for message in messages)
  assert not any('running-with-data' in message for message in messages)
  import json
  final = json.loads(next(message.removeprefix('FlexRay native: ') for message in reversed(messages) if message.startswith('FlexRay native: ')))
  assert 'gpio_setmode' in final['first_error']


def test_native_stderr_flood_does_not_block_socket_capture(tmp_path, monkeypatch):
  import sys
  from openpilot.system.flexray_logd import flexrayd

  messages = []
  monkeypatch.setattr(flexrayd.cloudlog, 'info', messages.append)
  child = tmp_path / 'stream.py'
  child.write_text("import os, signal, time\n"
                   + "signal.signal(signal.SIGINT, lambda *a: exit(0))\n"
                   + "while True: os.write(2,b'x'*8192)\n")
  calls = []
  monkeypatch.setattr(flexrayd, 'read_capture', lambda path: envelope())
  pm = SimpleNamespace(send=lambda service, message: calls.append(len(message.can)))
  start = time.monotonic()
  run_capture(pm, 'unused', lambda: len(calls) >= 10 or time.monotonic() - start > 3,
              binary=Path(sys.executable), capture_args=(str(child),))
  assert sum(calls) >= 10 and time.monotonic() - start < 3
  assert any('running-with-data' in message for message in messages)


def test_native_failure_reaches_rlog_via_cloudlog(tmp_path, monkeypatch):
  import sys
  from openpilot.common.swaglog import cloudlog, ipchandler
  from openpilot.tools.lib.logreader import LogReader

  log_root = tmp_path / 'logs'
  monkeypatch.setenv('LOG_ROOT', str(log_root))
  monkeypatch.setenv('LOGGERD_TEST', '1')
  monkeypatch.setenv('LOGGERD_SEGMENT_LENGTH', '60')
  pm = messaging.PubMaster(['flexray'])
  log_sub = messaging.sub_sock('logMessage', timeout=100, conflate=False)
  processes = []
  ipchandler.close()
  ipchandler.connect()
  try:
    # Match the device lifecycle: logmessaged is already running offroad;
    # loggerd subscribes when the vehicle goes onroad.
    processes.append(subprocess.Popen([sys.executable, '-m', 'openpilot.system.logmessaged'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
      cloudlog.info('FlexRay stderr bridge test ready')
      if messaging.recv_sock(log_sub) is not None:
        break
      time.sleep(0.05)
    else:
      pytest.fail('logmessaged did not receive cloudlog')
    processes.append(subprocess.Popen([str(Path(BASEDIR) / 'openpilot/system/loggerd/loggerd')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    assert pm.wait_for_readers_to_update('flexray', timeout=5)
    route_deadline = time.monotonic() + 5
    while Params().get('CurrentRoute') is None and time.monotonic() < route_deadline:
      time.sleep(0.01)
    assert Params().get('CurrentRoute') is not None
    from openpilot.system.flexray_logd import usb_inventory
    monkeypatch.setattr(usb_inventory, 'capture_usb_inventory', lambda: {'command': ['lsusb', '-v', '-d', '0403:6011'],
                                                                      'returncode': 0, 'output': 'mocked bcdDevice 08.00 saved-to-rlog'})
    inventory = usb_inventory.start_usb_inventory()
    inventory.thread.join(timeout=1)
    assert inventory.result is not None and 'saved-to-rlog' in inventory.result['output'], inventory.result
    inventory.report()
    assert inventory.reported
    descriptor_seen = False
    descriptor_deadline = time.monotonic() + 2
    while time.monotonic() < descriptor_deadline:
      event = messaging.recv_sock(log_sub, wait=True)
      if event is not None and 'FlexRay USB descriptor' in event.logMessage:
        descriptor_seen = True
        break
    assert descriptor_seen
    child = tmp_path / 'exit.py'
    child.write_text("import sys\nsys.stderr.write('native stage=usb_claim failed rc=-5 libusb=BUSY preserved-to-rlog\\n')\nsys.exit(1)")
    with pytest.raises(RuntimeError, match='status 1'):
      run_capture(pm, str(tmp_path / 'missing.sock'), lambda: False,
                  binary=Path(sys.executable), capture_args=(str(child),))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
      event = messaging.recv_sock(log_sub)
      if event is not None and 'preserved-to-rlog' in event.logMessage:
        break
    else:
      pytest.fail('native stderr was not forwarded through logMessage')
    # Ensure loggerd has consumed the logMessage before requesting final flush.
    time.sleep(0.15)
  finally:
    for process in reversed(processes):
      if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
          process.wait(timeout=5)
        except subprocess.TimeoutExpired:
          process.kill()
          process.wait()
    ipchandler.close()
    ipchandler.pid = None
  records = [event.logMessage for path in log_root.glob('*/rlog.zst') for event in LogReader(str(path)) if event.which() == 'logMessage']
  assert any('preserved-to-rlog' in record and 'stderr_eof' in record for record in records)
  assert any('FlexRay USB descriptor' in record and 'saved-to-rlog' in record for record in records)


def test_can_monitor_continues_during_native_retry(monkeypatch):
  from openpilot.system.flexray_logd import flexrayd

  handlers, observed = {}, []

  class Receiver:
    def __init__(self, bus):
      assert bus == 1

    def poll(self, now):
      observed.append(now)
      if len(observed) == 3:
        handlers[signal.SIGTERM](signal.SIGTERM, None)
      return {'bus': 1, 'complete_fresh': True}

  def failed_capture(*args, **kwargs):
    raise RuntimeError('native stage=usb_claim failed status 1')

  monkeypatch.setattr(flexrayd, 'Params', lambda: SimpleNamespace(get=lambda *args, **kwargs: 1))
  monkeypatch.setattr(flexrayd, 'DiagnosticReceiver', Receiver)
  monkeypatch.setattr(flexrayd, 'start_usb_inventory', lambda: None)
  monkeypatch.setattr(flexrayd, 'run_capture', failed_capture)
  monkeypatch.setattr(flexrayd.signal, 'signal', lambda sig, handler: handlers.__setitem__(sig, handler))
  monkeypatch.setattr(flexrayd.messaging, 'PubMaster', lambda services: SimpleNamespace(send=lambda *args: None))
  flexrayd.main()
  assert len(observed) == 3
