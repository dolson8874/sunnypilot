"""Optional independent replay: CRUISE_REAL_LOGS=segment1:segment2; can_validator on PYTHONPATH."""
import os

import pytest

from openpilot.system.cruise_analysis.observer import Observer


@pytest.mark.skipif(not os.getenv('CRUISE_REAL_LOGS'), reason='existing independent rlog paths not supplied')
def test_existing_logs_against_analysis_reference():
  from can_validator.radar_cycles import Cycles
  from openpilot.tools.lib.logreader import LogReader

  reference = Cycles()
  observer = Observer('independent-replay')
  checked = 0
  for path in os.environ['CRUISE_REAL_LOGS'].split(os.pathsep):
    for event_index, event in enumerate(LogReader(path)):
      if event.which() != 'can':
        continue
      before = len(reference.rows)
      observer.consume(event, int(event.logMonoTime), 'can')
      for frame_index, frame in enumerate(event.can):
        if frame.src == 1:
          reference.add(int(frame.address), bytes(frame.dat), int(event.logMonoTime), event_index, frame_index)
      assert len(reference.rows) == observer.radar.closed
      if len(reference.rows) > before:
        expected = reference.rows[-1]
        actual = observer.radar.last_closed
        assert actual['missingAddresses'] == expected['missing_ids']
        assert actual['counterMismatches'] == expected['low_nibble_mismatches']
        assert actual['lengthErrors'] == expected['length_mismatches']
        assert actual['duplicateFrames'] == sum(n - 1 for n in expected['duplicate_ids'].values())
        assert actual['firstEventMonoTime'] == expected['first_ns']
        assert actual['lastEventMonoTime'] == expected['last_ns']
        checked += 1
  assert checked > 0
  assert observer.radar.complete == sum(r['complete'] and r['low_nibble_mismatches'] == 0 for r in reference.rows)
