import pytest

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


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("transition", ["brake", "cancel"])
def test_mads_cancel_requires_fresh_acc_off_and_new_press(enabled, transition):
  decoder = RR2017StockCruise(mads_cancel_release=enabled)
  packer = CANPacker('landrover_rangerover_2017')
  released = packer.make_can_msg('CRUISE_ACC', 0, {'CruiseCancelRequestCandidate': 0})
  pressed = packer.make_can_msg('CRUISE_ACC', 0, {'CruiseCancelRequestCandidate': 1})
  acc_on = packer.make_can_msg('CRUISE_CONTROL', 0, {'CRUISE_ON': 1})
  acc_off = packer.make_can_msg('CRUISE_CONTROL', 0, {'DRIVER_BRAKE': transition == "brake"})
  gap4 = packer.make_can_msg('CR01', 0, {'GAP': 2})
  start = 1_000_000_000
  dt = 70_000_000

  for step, frames, expected in (
    (0, [acc_on, pressed], False),  # Startup with a held button.
    (1, [acc_on, released], False),
    (2, [acc_off, gap4, pressed if transition == "cancel" else released], False),
    (3, [acc_off, pressed if transition == "cancel" else released], False),
    (4, [acc_off, released], False),
    (5, [acc_off, (pressed[0], pressed[1], 2)], False),
    (6, [acc_off, pressed], enabled),
    (7, [acc_off, pressed], False),
    (8, [acc_off, released], False),
  ):
    stamp = start + step * dt
    _, gap = decoder.update([(stamp, frames)], stamp)
    if step == 2:
      assert gap == 4
    assert decoder.lkas_release_requested is expected


@pytest.mark.parametrize("reason", ["stale_acc", "stale_button", "invalid_can"])
def test_cancel_does_not_use_stale_input(reason):
  decoder = RR2017StockCruise(mads_cancel_release=True)
  packer = CANPacker('landrover_rangerover_2017')
  released = packer.make_can_msg('CRUISE_ACC', 0, {'CruiseCancelRequestCandidate': 0})
  pressed = packer.make_can_msg('CRUISE_ACC', 0, {'CruiseCancelRequestCandidate': 1})
  off = packer.make_can_msg('CRUISE_CONTROL', 0, {'CRUISE_ON': 0})
  start = 1_000_000_000
  dt = 70_000_000
  for tick in (0, 1, 2):
    stamp = start + tick * dt
    decoder.update([(stamp, [off, released])], stamp)
  if reason == "stale_button":
    for tick in range(3, 9):
      stamp = start + tick * dt
      decoder.update([(stamp, [off])], stamp)
  elif reason == "invalid_can":
    stamp = start + 3 * dt
    decoder.update([], stamp, can_valid=False)
  stamp = start + (9 if reason == "stale_button" else 4) * dt
  decoder.update([(stamp, [pressed])], stamp)
  assert not decoder.lkas_release_requested
