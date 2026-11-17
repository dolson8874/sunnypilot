"""Transport budget and optional-process failure isolation regression tests."""
import json
from types import SimpleNamespace

import pytest

from openpilot.cereal import messaging
from openpilot.cereal.services import SERVICE_LIST, QueueSize
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.system.cruise_analysis import analysisd
from openpilot.system.cruise_analysis.observer import Observer


def test_serialized_unicode_budget_and_minimal_fallback():
  observer = Observer('budget')
  observer.context['unicode'] = '가' * 80000
  message = analysisd.make_message(observer, 100)
  snapshot = json.loads(message.cruiseAnalysis.snapshotJson)
  assert snapshot['snapshotOmitted']
  assert snapshot['counts']['budgetExceeded'] == 1
  assert analysisd.message_fits(len(message.to_bytes()))
  observer.last_error = 'x' * 300000
  message = analysisd.make_message(observer, 200)
  snapshot = json.loads(message.cruiseAnalysis.snapshotJson)
  assert snapshot['epoch'] == 'budget' and 'lastError' not in snapshot
  assert snapshot['counts']['budgetExceeded'] == 2
  assert analysisd.message_fits(len(message.to_bytes()))


def test_queue_boundary_and_application_boundary(monkeypatch):
  monkeypatch.setattr(analysisd, 'MAX_SNAPSHOT_BYTES', 1000000)
  service = SERVICE_LIST['cruiseAnalysis']
  monkeypatch.setattr(service, 'queue_size', 250 * 1024)
  assert analysisd.message_fits(85320)
  assert not analysisd.message_fits(85321)
  monkeypatch.setattr(service, 'queue_size', QueueSize.MEDIUM)
  monkeypatch.setattr(analysisd, 'MAX_SNAPSHOT_BYTES', 200000)
  assert analysisd.message_fits(200000)
  assert not analysisd.message_fits(200001)


def test_impossible_queue_rejected_before_native_send(monkeypatch):
  monkeypatch.setattr(SERVICE_LIST['cruiseAnalysis'], 'queue_size', 8)
  with pytest.raises(ValueError, match='minimal snapshot'):
    analysisd.make_message(Observer('tiny'), 1)


def test_large_snapshot_real_msgq_roundtrip():
  assert SERVICE_LIST['cruiseAnalysis'].queue_size == QueueSize.MEDIUM
  observer = Observer('large')
  observer.context['test'] = 'x' * 110000
  raw = analysisd.make_message(observer, 100).to_bytes()
  assert len(raw) > 85320  # Previously aborted inside msgq, bypassing Python except.
  with OpenpilotPrefix():
    pub = messaging.PubMaster(['cruiseAnalysis'])
    sub = messaging.sub_sock('cruiseAnalysis', timeout=1000)
    pub.send('cruiseAnalysis', raw)
    assert sub.receive() == raw


@pytest.mark.parametrize('required', ['pandad', 'controlsd', 'card', 'selfdrived', 'modeld', 'loggerd', 'flexray_logd'])
def test_only_optional_processes_exempt(required):
  from openpilot.selfdrive.selfdrived.selfdrived import driving_processes_missing
  assert driving_processes_missing({'cruise_analysis', 'mapd'}) == set()
  assert driving_processes_missing({'cruise_analysis', 'mapd', required}) == {required}


def test_optional_observer_retry_backoff(monkeypatch):
  from openpilot.system.manager import process_config as config
  clock = [100.0]
  starts = []
  monkeypatch.setattr(config.time, 'monotonic', lambda: clock[0])

  def start(proc):
    starts.append(clock[0])
    proc.proc = SimpleNamespace(exitcode=None)

  monkeypatch.setattr(config.PythonProcess, 'start', start)
  monkeypatch.setattr(config.AnalysisProcess, 'stop', lambda proc: setattr(proc, 'proc', None))
  proc = config.AnalysisProcess('cruise_analysis', 'unused', lambda *args: True)
  proc.start()
  for delay in [1, 2, 4, 8, 16, 30, 30]:
    proc.proc.exitcode = -6
    clock[0] += 0.1
    before = len(starts)
    proc.start()
    assert proc.proc is None and len(starts) == before
    clock[0] = proc.retry_at - 0.01
    proc.start()
    assert len(starts) == before
    clock[0] += 0.01
    proc.start()
    assert len(starts) == before + 1
    assert clock[0] - starts[-2] >= delay
  clock[0] += 61
  proc.proc.exitcode = -6
  proc.start()
  assert proc.failures == 1 and proc.retry_at == clock[0] + 1


def test_actual_logs_published_and_recorded(tmp_path, monkeypatch):
  import os
  import signal
  import subprocess
  import time

  from openpilot.tools.lib.logreader import LogReader
  paths = os.getenv('CRUISE_QUEUE_LOGS')
  if not paths:
    pytest.skip('real route segments not supplied for transport replay')
  monkeypatch.setenv('LOG_ROOT', str(tmp_path / 'logs'))
  monkeypatch.setenv('LOGGERD_TEST', '1')
  monkeypatch.setenv('LOGGERD_SEGMENT_LENGTH', '60')
  expected = []
  large = 0
  with OpenpilotPrefix():
    pub = messaging.PubMaster(['cruiseAnalysis'])
    logger = subprocess.Popen(['openpilot/system/loggerd/loggerd'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
      assert pub.wait_for_readers_to_update('cruiseAnalysis', timeout=10)
      for path in paths.split(os.pathsep):
        observer = Observer('real-transport')
        last = 0
        for event in LogReader(path):
          kind = event.which()
          if kind in analysisd.INPUTS:
            transport = 'flexray' if kind == 'can' and any(f.src in (4, 5, 6) for f in event.can) else kind
            analysisd.consume_raw(observer, transport, event.as_builder().to_bytes(), event.logMonoTime)
          if event.logMonoTime - last >= 500000000:
            raw = analysisd.make_message(observer, event.logMonoTime).to_bytes()
            assert analysisd.message_fits(len(raw))
            pub.send('cruiseAnalysis', raw)
            assert pub.wait_for_readers_to_update('cruiseAnalysis', timeout=5)
            expected.append(raw)
            large += len(raw) > 85320
            last = event.logMonoTime
      assert large > 0 and logger.poll() is None
      time.sleep(.1)
    finally:
      logger.send_signal(signal.SIGINT)
      logger.wait(timeout=10)
    assert logger.returncode == 0
    recorded = [event.as_builder().to_bytes() for path in sorted((tmp_path / 'logs').glob('*/rlog.zst'))
                for event in LogReader(str(path)) if event.which() == 'cruiseAnalysis']
    assert recorded == expected
    print(f'real transport replay: snapshots={len(expected)} formerly_oversized={large}')
