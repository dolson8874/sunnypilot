from opendbc.can.packer import CANPacker
from openpilot.selfdrive.car.rr2017_cruise import FRESH_NS, RR2017StockCruise


def test_stock_acc_validity_and_independent_expiry():
  decoder = RR2017StockCruise()
  packer = CANPacker('landrover_rangerover_2017')
  stamp = 1_000_000_000
  assert decoder.update([], stamp) == (0, 0)

  speed = packer.make_can_msg('CR00', 0, {'VSetDist': 84.25})
  for encoded, expected_gap in enumerate((3, 2, 4, 1)):
    stamp += 1
    gap = packer.make_can_msg('CR01', 0, {'GAP': encoded})
    gap = (gap[0], gap[1][:-1] + bytes([gap[1][-1] | 20]), gap[2])
    assert decoder.update([(stamp, [speed, gap])], stamp) == (84.25, expected_gap)

  expiry = stamp + FRESH_NS
  invalid_packets = [(speed[0], speed[1], 2), (gap[0], gap[1][:-1], 0)]
  assert decoder.update([(expiry, invalid_packets)], expiry) == (0, 0)
  assert decoder.update([(expiry, [gap])], expiry) == (0, 1)
  assert decoder.update([], expiry - 1) == (84.25, 0)


def test_mads_gap_release_requires_a_button_and_fresh_transition():
  packer = CANPacker('landrover_rangerover_2017')
  released = packer.make_can_msg('CRUISE_ACC', 0, {'GapBtn1': 0})
  pressed = packer.make_can_msg('CRUISE_ACC', 0, {'GapBtn1': 1})
  gap3 = packer.make_can_msg('CR01', 0, {'GAP': 0})
  gap4 = packer.make_can_msg('CR01', 0, {'GAP': 2})
  start = 1_000_000_000
  dt = 70_000_000

  for enabled in (False, True):
    decoder = RR2017StockCruise(mads_gap_release=enabled)
    for ts, frames, expected in (
      (start, [gap4, pressed], False),  # startup at Gap 4 with an already held button
      (start + dt, [gap3, released], False),
      (start + 2 * dt, [gap4, released], False),  # Gap status alone
      (start + 3 * dt, [gap3, released], False),
      (start + 4 * dt, [gap4, pressed], enabled),  # same CAN batch, either frame order
      (start + 5 * dt, [gap4, pressed], False),
      (start + 6 * dt, [gap3, released], False),  # leaving Gap 4 emits no request
    ):
      decoder.update([(ts, frames)], ts)
      assert decoder.gap_release_requested is expected

  for invalidate in ('gap', 'button', 'can'):
    decoder = RR2017StockCruise(mads_gap_release=True)
    decoder.update([(start, [gap3, released])], start)
    decoder.update([(start + dt, [gap3, pressed])], start + dt)
    if invalidate == 'can':
      decoder.update([], start + 2 * dt, can_valid=False)
      stamp = start + 3 * dt
    else:
      stamp = start + dt + FRESH_NS
      for offset in (dt, 2 * dt, 3 * dt):
        stamp2 = start + dt + offset
        frames = [pressed] if invalidate == 'gap' else [gap3]
        decoder.update([(stamp2, frames)], stamp2)
    decoder.update([(stamp, [gap4])], stamp)
    assert not decoder.gap_release_requested
