import json
import tempfile
import unittest

from openpilot.cereal import messaging
from openpilot.system.cruise_analysis.analysisd import consume_raw, make_message
from openpilot.system.cruise_analysis.observer import Observer


def can(src, address, data, stamp=100):
  event = messaging.new_message('can', 1)
  event.valid = True
  event.logMonoTime = stamp
  event.can[0] = {'src': src, 'address': address, 'dat': data}
  return event


class TestObserver(unittest.TestCase):
  def test_raw_and_exclusions(self):
    o = Observer('test')
    raw = bytes([4, 1]) + bytes(range(26)) + b'crc'
    event = can(6, 31, raw)
    before = event.to_bytes()
    o.consume(event, 200, 'flexray')
    event.clear_write_flag()
    self.assertEqual(event.to_bytes(), before)
    record = o.snapshot(1000)['frames']['6:31:1']
    self.assertEqual(record['hex'], raw.hex())
    self.assertEqual(record['values']['dadcRaw16'], int.from_bytes(raw[11:13], 'big'))
    self.assertIsNone(record['excluded'])
    for data, reason in ((raw[:10], 'length'), (bytes([0]) + raw[1:], 'nfi0')):
      o.consume(can(6, 31, data), 300, 'flexray')
      self.assertEqual(o.snapshot(1000)['frames']['6:31:1']['excluded'], reason)
    o.consume(can(6, 31, bytes(259)), 400, 'flexray')
    self.assertEqual(o.frames['6:31:0']['length'], 259)
    self.assertEqual(o.frames['6:31:0']['excluded'], 'length')

  def test_src_and_diagnostics(self):
    o = Observer()
    for src, address in ((1, 0x1fa), (1, 0x1f0), (1, 0x1f9), (2, 0x200), (129, 0x200), (193, 0x200), (6, 31)):
      o.consume(can(src, address, bytes(8)), 200)
    self.assertEqual(o.frames, {})

  def test_slots_zero_partial_reuse_conflicts(self):
    o = Observer()
    for slot in range(40):
      for member in range(6):
        raw = bytes(7 if member == 4 else 8)
        o.consume(can(1, 0x200 + slot * 16 + member, raw), 200)
    snap = o.snapshot(1000)
    self.assertEqual(len(snap['slots']), 40)
    self.assertTrue(all(s['memberMask'] == 63 for s in snap['slots']))
    self.assertEqual(snap['slots'][0]['indexRaw'], 0)
    self.assertEqual(snap['slots'][0]['assembly'], 'notAssembled')
    o.consume(can(1, 0x200, b'\x01' + bytes(7)), 300)
    self.assertEqual(o.counts['conflicts'], 1)
    self.assertEqual(Observer().snapshot(1)['slots'][0]['memberMask'], 0)
    self.assertNotEqual(Observer().epoch, o.epoch)

  def test_time_and_wheels(self):
    o = Observer()
    event = messaging.new_message('carState')
    event.valid = True
    for stamp, value in ((0, 0.), (500000000, 1.)):
      event.logMonoTime = stamp
      event.carState.wheelSpeeds = {'fl': value, 'fr': value, 'rl': value, 'rr': value}
      o.consume(event, stamp)
    self.assertEqual(o.wheel_change['perWheelDeltaVPerSecond'], [2.] * 4)
    o.consume(event, stamp)
    self.assertIsNone(o.wheel_change['perWheelDeltaVPerSecond'])

  def test_raw_error_isolation_and_recovery(self):
    o = Observer()
    consume_raw(o, 'can', b'bad', 100)
    self.assertEqual(o.counts['errors'], 1)
    self.assertTrue(o.last_error)
    consume_raw(o, 'can', bytes((1 << 20) + 1), 200)
    self.assertEqual(o.counts['budgetExceeded'], 1)
    consume_raw(o, 'carState', can(0, 0x10c, bytes(8)).to_bytes(), 300)
    self.assertEqual(o.counts['rejected'], 1)
    consume_raw(o, 'can', can(0, 0x10c, bytes(8)).to_bytes(), 400)
    self.assertIn('0:268:-1', o.frames)
    self.assertEqual(o.counts['errors'], 1)

  def test_host_freshness_and_wheel_gap(self):
    o = Observer()
    o.consume(can(0, 0x10c, bytes(8), stamp=100), 200)
    self.assertEqual(o.snapshot(1000000099)['frames']['0:268:-1']['freshness'], 'recent')
    self.assertEqual(o.snapshot(1000000100)['frames']['0:268:-1']['freshness'], 'stale')
    self.assertEqual(o.snapshot(99)['frames']['0:268:-1']['freshness'], 'clockConflict')
    event = messaging.new_message('carState')
    event.valid = True
    event.carState.wheelSpeeds = {'fl': 1., 'fr': 1., 'rl': 1., 'rr': 1.}
    for stamp in (100, 1000000100):
      event.logMonoTime = stamp
      o.consume(event, stamp)
    self.assertEqual(o.wheel_change['reason'], 'hostGapExceeded')
    self.assertIsNone(o.wheel_change['perWheelDeltaVPerSecond'])

  def test_radar_publication_boundaries(self):
    from openpilot.system.cruise_analysis.radar import EXPECTED
    o = Observer()
    o.consume(can(1, 0x200, bytes(8)), 100)
    self.assertEqual(o.radar.pre_boundary, 1)
    for address in sorted(EXPECTED):
      o.consume(can(1, address, bytes(7 if address >= 0x200 and address % 16 == 4 else 8)), 200)
    o.consume(can(1, 0x190, bytes(8)), 300)
    self.assertTrue(o.radar.last_closed['completeCandidate'])
    self.assertEqual(o.radar.closed, 1)
    o.consume(can(1, 0x200, bytes([1]) + bytes(7)), 400)
    o.consume(can(1, 0x200, bytes(8)), 400)
    o.consume(can(1, 0x190, bytes(8)), 500)
    self.assertFalse(o.radar.last_closed['completeCandidate'])
    self.assertEqual(o.radar.last_closed['duplicateFrames'], 1)
    self.assertEqual(o.radar.last_closed['counterMismatches'], 1)
    self.assertEqual(o.radar.summary()['sequence'], 3)

  def test_invalid_clock_and_budget(self):
    o = Observer()
    event = can(0, 0x10c, bytes(8), stamp=1000)
    event.valid = False
    o.consume(event, 2000)
    frame = o.snapshot(900)['frames']['0:268:-1']
    self.assertEqual(frame['excluded'], 'invalidEvent')
    self.assertEqual(frame['freshness'], 'clockConflict')
    event = messaging.new_message('can', 4097)
    event.valid = True
    o.consume(event, 3000)
    self.assertEqual(o.counts['budgetExceeded'], 1)

  def test_bytes_nonfinite_and_recovery(self):
    o = Observer()
    o.context['test'] = {'bytes': b'abc', 'number': float('nan')}
    data = json.loads(make_message(o, 100).cruiseAnalysis.snapshotJson)
    self.assertEqual(data['context']['test']['bytes'], {'bytesHex': '616263'})
    self.assertEqual(data['context']['test']['number'], {'nonFinite': 'nan'})
    o.consume(can(6, 31, bytes([4, 1]) + bytes(29)), 300, 'flexray')
    self.assertIsNone(o.frames['6:31:1']['excluded'])
    o.context['large'] = 'a' * 250000
    snapshot = json.loads(make_message(o, 400).cruiseAnalysis.snapshotJson)
    self.assertEqual(snapshot['snapshotOmitted'], 'sizeBudget;seeOriginalRlogEvents')

  def test_rlog_round_trip_and_segment_restart(self):
    o = Observer('test')
    event = can(0, 0x10c, bytes(8))
    o.consume(event, 200)
    message = make_message(o, 300)
    # The logger stores serialized Event messages; test concatenated original + observation and segment files.
    from openpilot.cereal import log
    with tempfile.TemporaryFile() as f:
      f.write(event.to_bytes() + message.to_bytes())
      f.seek(0)
      readers = list(log.Event.read_multiple(f))
      self.assertEqual([r.which() for r in readers], ['can', 'cruiseAnalysis'])
      data = json.loads(readers[1].cruiseAnalysis.snapshotJson)
      self.assertEqual(data['epoch'], 'test')
      self.assertEqual(data['frames']['0:268:-1']['hex'], bytes(8).hex())
      self.assertEqual(data['fpgaBeforeAfter'], 'unknown')
      self.assertEqual(readers[0].can[0].dat, bytes(8))
    self.assertEqual(make_message(o, 10000000000).cruiseAnalysis.version, 1)


if __name__ == '__main__':
  unittest.main()
