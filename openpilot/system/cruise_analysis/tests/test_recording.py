"""Opt-in native integration: CRUISE_INTEGRATION=1 pytest .../test_recording.py."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

import pytest

from openpilot.cereal import messaging
from openpilot.common.params import Params
from openpilot.tools.lib.logreader import LogReader

pytestmark = pytest.mark.skipif(os.getenv('CRUISE_INTEGRATION') != '1', reason='65-second native recording test')


def test_rotation_restart_and_display_isolation(tmp_path, monkeypatch):
  prefix = 'cruise-integration-' + uuid.uuid4().hex
  shm = Path('/dev/shm/msgq_' + prefix)
  shm.mkdir()
  monkeypatch.setenv('OPENPILOT_PREFIX', prefix)
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path / 'params'))
  monkeypatch.setenv('PARAMS_COPY_PATH', str(tmp_path / 'params'))
  monkeypatch.setenv('LOG_ROOT', str(tmp_path / 'logs'))
  monkeypatch.delenv('LOGGERD_TEST', raising=False)
  params = Params()
  params.put_bool('CruiseAnalysisShow', False, block=True)
  services = ['can', 'flexray', 'carState', 'carControl', 'sendcan', 'radarTracks']
  pm = messaging.PubMaster(services)
  expected = {kind: [] for kind in ('carState', 'carControl', 'sendcan', 'radarTracks')}
  expected_can = []
  processes = []
  log_file = (tmp_path / 'process.log').open('wb')

  def start_observer():
    p = subprocess.Popen([os.sys.executable, '-m', 'openpilot.system.cruise_analysis.analysisd'], stdout=log_file, stderr=log_file)
    processes.append(p)
    return p

  try:
    logger = subprocess.Popen(['openpilot/system/loggerd/loggerd'], stdout=log_file, stderr=log_file)
    processes.append(logger)
    for service in services:
      assert pm.wait_for_readers_to_update(service, timeout=10)
    observer = start_observer()
    start = time.monotonic()
    toggled = restarted = paused = resumed = False
    seq = 0
    while time.monotonic() - start < 63:
      elapsed = time.monotonic() - start
      if elapsed >= 5 and not toggled:
        params.put_bool('CruiseAnalysisShow', True, block=True)
        toggled = True
      if elapsed >= 10 and not restarted:
        observer.terminate()
        observer.wait(timeout=5)
        observer = start_observer()
        restarted = True
      if elapsed >= 15 and not paused:
        observer.send_signal(signal.SIGSTOP)
        paused = True
      if elapsed >= 18 and not resumed:
        observer.send_signal(signal.SIGCONT)
        resumed = True
      for kind in expected:
        event = messaging.new_message(kind, 1) if kind == 'sendcan' else messaging.new_message(kind)
        event.valid = True
        event.logMonoTime = 1000000000 + seq
        if kind == 'sendcan':
          event.sendcan[0] = {'src': 1, 'address': 0x1f0, 'dat': seq.to_bytes(8, 'little')}
        elif kind == 'carState':
          event.carState.vEgo = seq % 20
        expected[kind].append(event.to_bytes())
        pm.send(kind, expected[kind][-1])
      event = messaging.new_message('can', 2)
      event.valid = True
      event.logMonoTime = 1000000000 + seq
      event.can[0] = {'src': 0, 'address': 0x123, 'dat': seq.to_bytes(8, 'little')}
      event.can[1] = {'src': 2, 'address': 0x123, 'dat': seq.to_bytes(8, 'little')}
      raw = event.to_bytes()
      expected_can.append(raw)
      pm.send('can', raw)
      event = messaging.new_message('can', 1)
      event.valid = True
      event.logMonoTime = 1000000000 + seq
      event.can[0] = {'src': 6, 'address': 31, 'dat': bytes([4, 1]) + bytes(254) + b'crc'}
      raw = event.to_bytes()
      expected_can.append(raw)
      pm.send('flexray', raw)
      # msgq retains dead-reader acknowledgement slots after a subscriber exits.
      # Use logger-only channels for pacing; verify raw streams from the resulting rlog.
      for service in ('sendcan', 'radarTracks'):
        assert pm.wait_for_readers_to_update(service, timeout=5)
      seq += 1
      time.sleep(.1)
    observer.terminate()
    observer.wait(timeout=5)
    logger.send_signal(signal.SIGINT)
    logger.wait(timeout=10)
    assert logger.returncode == 0
    files = sorted((tmp_path / 'logs').glob('*/rlog.zst'))
    assert len(files) >= 2
    events = [list(LogReader(str(path))) for path in files]
    assert all(any(e.which() == 'cruiseAnalysis' for e in segment) for segment in events)
    flattened = [e for segment in events for e in segment]
    for kind, messages in expected.items():
      assert [e.as_builder().to_bytes() for e in flattened if e.which() == kind] == messages
    # can and flexray are independent services, so assert order within each original source stream.
    recorded = [e for e in flattened if e.which() == 'can']
    for src in (0, 6):
      actual = [e.as_builder().to_bytes() for e in recorded if e.can[0].src == src]
      originals = expected_can[0::2] if src == 0 else expected_can[1::2]
      assert actual == originals
    snapshots = [json.loads(e.cruiseAnalysis.snapshotJson) for e in flattened if e.which() == 'cruiseAnalysis']
    assert len({s['epoch'] for s in snapshots}) == 2
    assert all(s['fpgaBeforeAfter'] == 'unknown' for s in snapshots)
    assert any(s['frames'].get('6:31:1', {}).get('length') == 259 for s in snapshots)
  finally:
    for p in reversed(processes):
      if p.poll() is None:
        p.send_signal(signal.SIGCONT)
        p.terminate()
        p.wait(timeout=10)
    log_file.close()
    import shutil
    shutil.rmtree(shm)
