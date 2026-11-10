from types import SimpleNamespace

from openpilot.cereal import messaging
from openpilot.system.flexray_logd.startup import LoggerStartup
from openpilot.system.flexray_logd.status import CaptureStatus


def setup(capacity=4096):
  sent, clock, values = [], [10.0], {}
  pm = SimpleNamespace(send=lambda service, message: sent.append((service, message)))
  telemetry = CaptureStatus(pm, clock=lambda: clock[0])
  gate = LoggerStartup(pm, SimpleNamespace(get=lambda key: values.get(key)), telemetry, clock=lambda: clock[0], capacity=capacity)
  return gate, telemetry, sent, clock, values


def frames():
  return [{'address': 13, 'src': 6, 'dat': b'\x03\x07\x12\x34\x56'},
          {'address': 6, 'src': 4, 'dat': b'\x01\x02\x34\x56\x78'}]


def test_probe_ack_before_lossless_ordered_flush():
  gate, telemetry, sent, clock, values = setup()
  gate.poll()
  first_probe = gate.probes[-1]
  gate.submit(frames())
  gate.submit(frames())
  gate.poll()
  assert gate.buffered_frames == 4 and not gate.ready
  assert telemetry.snapshot()['state'] == 'buffering'
  assert all(not isinstance(message, bytes) for _, message in sent)
  values['FlexrayLoggerAck'] = str(first_probe - 1)  # Old collector/route cannot unlock this session.
  clock[0] += 0.1
  gate.poll()
  assert not gate.ready
  values['FlexrayLoggerAck'] = str(first_probe)
  clock[0] += 0.1
  gate.poll()
  assert gate.ready and gate.buffered_bytes == 0 and gate.buffered_frames == 0
  recorded = []
  for _service, raw in sent:
    if isinstance(raw, bytes):
      with messaging.log.Event.from_bytes(raw) as event:
        assert event.valid and event.which() == 'can'
        recorded.extend({'address': f.address, 'src': f.src, 'dat': bytes(f.dat)} for f in event.can)
  assert recorded == frames() * 2
  assert telemetry.counts == {4: 2, 6: 2}
  assert telemetry.logger['loggerReady']
  assert gate.dropped_frames == 0


def test_bounded_overflow_does_not_stop_input_and_shutdown_accounts_loss():
  gate, telemetry, sent, clock, values = setup(capacity=300)
  for _ in range(100):
    gate.submit(frames())
    gate.poll()
  assert gate.buffered_bytes <= 300 and gate.dropped_frames > 0
  assert gate.buffered_frames + gate.dropped_frames == 200
  gate.close()
  assert gate.buffered_bytes == 0 and gate.dropped_frames == 200
  assert telemetry.logger['startupDroppedFrames'] == 200
  assert len(gate.probes) <= 16


def test_delayed_ack_flush_keeps_earlier_receive_time_and_new_frames_work():
  gate, telemetry, sent, clock, values = setup()
  gate.submit(frames())
  gate.poll()
  values['FlexrayLoggerAck'] = str(gate.probes[-1])
  clock[0] += 1
  gate.poll()
  assert telemetry.last_frame == 10
  gate.submit(frames())
  assert telemetry.last_frame == 11 and telemetry.counts == {4: 2, 6: 2}
  assert not gate.queue


def test_real_logger_starts_after_frames_and_preserves_every_frame(tmp_path, monkeypatch):
  import signal
  import subprocess
  import time
  from pathlib import Path
  from openpilot.common.basedir import BASEDIR
  from openpilot.common.params import Params
  from openpilot.common.prefix import OpenpilotPrefix
  from openpilot.tools.lib.logreader import LogReader

  with OpenpilotPrefix():
    log_root = tmp_path / 'logs'
    monkeypatch.setenv('LOG_ROOT', str(log_root))
    monkeypatch.setenv('LOGGERD_TEST', '1')
    monkeypatch.setenv('LOGGERD_SEGMENT_LENGTH', '60')
    pm = messaging.PubMaster(['flexray', 'flexrayStatus'])
    params = Params()
    params.put('FlexrayLoggerAck', '12345', block=True)
    telemetry = CaptureStatus(pm)
    gate = LoggerStartup(pm, params, telemetry)
    expected = []
    for index in range(100):
      batch = frames()
      batch[0]['address'] += index
      if index == 0:
        batch[1]['dat'] = b'\x03\x07' + bytes(range(254)) + b'\x12\x34\x56'
      expected.extend(batch)
      gate.submit(batch)
    gate.poll()
    assert not gate.ready and gate.buffered_frames == 200
    process = subprocess.Popen([str(Path(BASEDIR) / 'openpilot/system/loggerd/loggerd')],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
      deadline = time.monotonic() + 5
      while not gate.ready and time.monotonic() < deadline:
        assert process.poll() is None
        gate.poll()
        time.sleep(0.02)
      assert gate.ready and gate.buffered_frames == 0
      for _ in range(20):
        expected.extend(frames())
        gate.submit(frames())
      assert pm.wait_for_readers_to_update('flexray', timeout=5)
      gate.close()
      assert gate.dropped_frames == 0
    finally:
      if process.poll() is None:
        process.send_signal(signal.SIGINT)
      process.wait(timeout=5)
    recorded = [
      {'address': f.address, 'src': f.src, 'dat': bytes(f.dat)}
      for path in log_root.glob('*/rlog.zst') for event in LogReader(str(path)) if event.which() == 'can'
      for f in event.can
    ]
    assert recorded == expected
    assert telemetry.counts == {4: 120, 6: 120}


def test_buffer_flush_does_not_inflate_receive_rate():
  gate, telemetry, sent, clock, values = setup()
  for _tick in range(5):
    gate.submit(frames())
    gate.poll()
    clock[0] += 1
    telemetry.publish()
  assert telemetry.counts == {4: 0, 6: 0}
  values['FlexrayLoggerAck'] = str(gate.probes[-1])
  gate.poll()
  assert gate.ready and telemetry.counts == {4: 5, 6: 5}
  assert telemetry.rates == {4: 1.0, 6: 1.0}
  assert telemetry.arrival_counts == {4: 5, 6: 5}


def test_direct_send_failure_buffers_then_recovers_without_loss():
  gate, telemetry, sent, clock, values = setup()
  gate.ready = True
  original_send = gate.pm.send

  def failed_send(*args):
    raise OSError('simulated IPC send failure')

  gate.pm.send = failed_send
  gate.submit(frames())
  assert not gate.ready and gate.buffered_frames == 2
  assert telemetry.counts == {4: 0, 6: 0} and gate.dropped_frames == 0
  gate.pm.send = original_send
  clock[0] += 0.3
  gate.poll()
  values['FlexrayLoggerAck'] = str(gate.probes[-1])
  clock[0] += 0.1
  gate.poll()
  assert gate.ready and gate.buffered_frames == 0
  assert telemetry.counts == {4: 1, 6: 1}
  assert gate.buffered_bytes == 0 and gate.dropped_bytes == 0


def test_failed_queued_send_preserves_queue_and_shutdown_accounts_it():
  gate, telemetry, sent, clock, values = setup()
  gate.submit(frames())
  gate.submit(frames())
  size = gate.buffered_bytes
  gate.poll()
  values['FlexrayLoggerAck'] = str(gate.probes[-1])
  original_send = gate.pm.send

  def failed_data(service, data):
    if isinstance(data, bytes):
      raise OSError('simulated data failure')
    original_send(service, data)

  gate.pm.send = failed_data
  clock[0] += 0.1
  gate.poll()
  assert not gate.ready and len(gate.queue) == 2
  assert gate.buffered_bytes == size and gate.buffered_frames == 4
  assert telemetry.counts == {4: 0, 6: 0}
  gate.close()
  assert not gate.queue and gate.dropped_frames == 4 and gate.dropped_bytes == size
  assert gate.buffered_bytes == 0


def test_probe_and_ack_errors_do_not_stop_buffering(monkeypatch):
  from msgq import IpcError
  from openpilot.system.flexray_logd import startup

  gate, telemetry, sent, clock, values = setup()
  errors = []
  monkeypatch.setattr(startup.cloudlog, 'error', errors.append)

  def failed_probe(*args):
    raise IpcError()

  gate.pm.send = failed_probe
  gate.submit(frames())
  gate.poll()
  assert not gate.ready and not gate.probes and gate.buffered_frames == 2
  assert gate.transport_failures == 1 and 'send_probe' in telemetry.last_error
  gate.pm.send = lambda *args: None

  def failed_ack(key):
    raise OSError('ack unavailable')

  gate.params.get = failed_ack
  clock[0] += 0.3
  gate.poll()
  assert 'logger_ack_read' in telemetry.last_error
  assert gate.buffered_frames == 2 and len(errors) == 1  # Error reports are rate limited.


def test_close_has_a_deadline_and_counts_unflushed_frames(monkeypatch):
  from openpilot.system.flexray_logd import startup

  gate, telemetry, sent, clock, values = setup(capacity=32768)
  for _ in range(50):
    gate.submit(frames())
  original_size = gate.buffered_bytes
  gate.ready = True
  monkeypatch.setattr(startup, 'FLUSH_BYTES', 1)

  def slow_send(service, data):
    clock[0] += 0.6
    sent.append((service, data))

  gate.pm.send = slow_send
  gate.close()
  assert len(sent) == 2 and gate.dropped_frames == 96
  assert telemetry.counts == {4: 2, 6: 2}
  assert gate.dropped_bytes + sum(len(data) for _, data in sent) == original_size
  assert not gate.queue and gate.buffered_frames == 0
