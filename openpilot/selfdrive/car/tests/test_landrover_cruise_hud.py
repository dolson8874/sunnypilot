import pytest

from openpilot.cereal import messaging
from openpilot.selfdrive.car.helpers import convert_to_capnp
from openpilot.selfdrive.pandad import can_capnp_to_list
from opendbc.car import Bus
from opendbc.car.landrover.interface import CarInterface
from opendbc.car.landrover.landrovercan import defender_crc
from opendbc.car.landrover.values import CAR, LandroverFlags
from opendbc.safety import ALTERNATIVE_EXPERIENCE


DEFENDER_CAN0 = [(addr, bytes(8), 0) for addr in (
  0x11, 0x24, 0x2E, 0x32, 0x56, 0x84, 0xBF, 0xE6, 0xED, 0xF0, 0x102, 0x108, 0x189, 0x18F, 0x28F,
)]


def decode_can(timestamp_ns, frames):
  event = messaging.new_message('can', size=len(frames), logMonoTime=timestamp_ns)
  for msg, (address, data, bus) in zip(event.can, frames, strict=True):
    msg.address, msg.dat, msg.src = address, data, bus
  return can_capnp_to_list([event.to_bytes()])


def hud(flags, mode, counter, set_speed=0, gap=0):
  payload = bytes([flags | counter, mode | (gap << 3), set_speed, 0, 0, 0, 0])
  return bytes([defender_crc(payload[:4])]) + payload


def test_defender_cruise_hud_accepts_card_can_batches(monkeypatch):
  monkeypatch.delenv('LANDROVER_CRUISE_HUD_BENCH', raising=False)
  monkeypatch.setenv('REPLAY', '1')
  cp = CarInterface.get_non_essential_params(CAR.LANDROVER_DEFENDER_2023)
  cp_sp = CarInterface.get_non_essential_params_sp(cp, CAR.LANDROVER_DEFENDER_2023)
  assert cp.flags & LandroverFlags.CRUISE_HUD_BENCH
  interface = CarInterface(cp, cp_sp)
  assert interface.can_parsers[Bus.adas].bus == 1
  assert interface.can_parsers[Bus.adas].addresses == {0x1FB}
  normal_can = DEFENDER_CAN0

  state, _ = interface.update(decode_can(1_000_000_000, normal_can))
  assert not state.cruiseState.enabled
  assert state.blockPcmEnable
  assert not state.canValid
  assert state.canTimeout

  off, on = hud(0x80, 0, 15, 82), hud(0x30, 3, 0, 82)
  state, _ = interface.update(decode_can(1_050_000_000, normal_can + [(0x1FB, off, 1)]))
  assert not state.cruiseState.enabled
  assert state.cruiseState.speed == 0
  state, _ = interface.update(decode_can(1_100_000_000, normal_can + [(0x1FB, on, 0)]))
  assert not state.cruiseState.enabled
  state, _ = interface.update(decode_can(1_150_000_000, normal_can + [(0x1FB, on, 1)]))
  assert state.cruiseState.enabled
  assert state.cruiseState.speed == pytest.approx(82 / 3.6)
  assert state.cruiseState.speedCluster == state.cruiseState.speed
  assert state.cruiseState.speed != state.vEgoRaw
  assert not state.blockPcmEnable
  assert state.canValid
  assert not state.canTimeout


@pytest.mark.parametrize("bad_input", ["missing", "other_can1", "wrong_bus", "short_dlc", "bad_crc", "reserved", "duplicate"])
def test_defender_requires_fresh_valid_can1_hud(monkeypatch, bad_input):
  monkeypatch.delenv('LANDROVER_CRUISE_HUD_BENCH', raising=False)
  monkeypatch.setenv('REPLAY', '1')
  cp = CarInterface.get_non_essential_params(CAR.LANDROVER_DEFENDER_2023)
  cp_sp = CarInterface.get_non_essential_params_sp(cp, CAR.LANDROVER_DEFENDER_2023)
  interface = CarInterface(cp, cp_sp)
  pt = DEFENDER_CAN0
  interface.update(decode_can(950_000_000, pt))
  data = hud(0x30, 3, 15, 82)
  state, _ = interface.update(decode_can(1_000_000_000, pt + [(0x1FB, data, 1)]))
  assert state.canValid
  assert state.cruiseState.speed == pytest.approx(82 / 3.6)
  next_data = hud(0x30, 3, 0, 90)
  reserved = bytearray(next_data)
  reserved[2] |= 0x20
  reserved[0] = defender_crc(reserved[1:5])
  inputs = {
    "missing": [],
    "other_can1": [(0x1FA, bytes(8), 1)],
    "wrong_bus": [(0x1FB, next_data, 2)],
    "short_dlc": [(0x1FB, next_data[:-1], 1)],
    "bad_crc": [(0x1FB, bytes([next_data[0] ^ 1]) + next_data[1:], 1)],
    "reserved": [(0x1FB, bytes(reserved), 1)],
    "duplicate": [(0x1FB, data, 1)],
  }
  for elapsed_ms in (50, 100, 150):
    interface.update(decode_can(1_000_000_000 + elapsed_ms * 1_000_000, pt + inputs[bad_input]))
  state, state_sp = interface.update(decode_can(1_200_000_000, pt))
  assert not state.canValid
  assert not state.cruiseState.enabled
  assert state.cruiseState.speed == 0
  assert state_sp.stockCruiseGap == 0
  state, _ = interface.update(decode_can(1_250_000_000, pt + [(0x1FB, next_data, 1)]))
  assert state.canValid
  assert state.cruiseState.enabled
  assert state.cruiseState.speed == pytest.approx(90 / 3.6)
  assert state.blockPcmEnable


def test_defender_legacy_cruise_does_not_require_can1(monkeypatch):
  monkeypatch.setenv('LANDROVER_CRUISE_HUD_BENCH', '0')
  monkeypatch.setenv('REPLAY', '1')
  cp = CarInterface.get_non_essential_params(CAR.LANDROVER_DEFENDER_2023)
  cp_sp = CarInterface.get_non_essential_params_sp(cp, CAR.LANDROVER_DEFENDER_2023)
  interface = CarInterface(cp, cp_sp)
  assert Bus.adas not in interface.can_parsers
  interface.update(decode_can(950_000_000, DEFENDER_CAN0))
  state, _ = interface.update(decode_can(1_000_000_000, DEFENDER_CAN0))
  assert state.canValid
  assert not state.canTimeout
  assert state.cruiseState.speed == state.vEgoRaw


@pytest.mark.parametrize("flags,mode,h", [(0x30, 3, 0), (0x30, 3, 255), (0xC0, 6, 80), (0x30, 4, 80)])
def test_defender_hud_does_not_publish_unavailable_set_speed(monkeypatch, flags, mode, h):
  monkeypatch.delenv('LANDROVER_CRUISE_HUD_BENCH', raising=False)
  monkeypatch.setenv('REPLAY', '1')
  cp = CarInterface.get_non_essential_params(CAR.LANDROVER_DEFENDER_2023)
  cp_sp = CarInterface.get_non_essential_params_sp(cp, CAR.LANDROVER_DEFENDER_2023)
  interface = CarInterface(cp, cp_sp)
  good = (0x1FB, hud(0x30, 3, 0, 82), 1)
  invalid = (0x1FB, hud(flags, mode, 1, h), 1)
  interface.update(decode_can(1_000_000_000, DEFENDER_CAN0 + [good]))
  state, _ = interface.update(decode_can(1_050_000_000, DEFENDER_CAN0 + [invalid]))
  assert state.cruiseState.speed == 0
  assert state.cruiseState.speedCluster == 0


@pytest.mark.parametrize("raw,level", [(3, 1), (1, 2), (0, 3), (2, 4)])
def test_defender_stock_gap_only_in_active_hud(monkeypatch, raw, level):
  monkeypatch.delenv('LANDROVER_CRUISE_HUD_BENCH', raising=False)
  monkeypatch.setenv('REPLAY', '1')
  cp = CarInterface.get_non_essential_params(CAR.LANDROVER_DEFENDER_2023)
  cp_sp = CarInterface.get_non_essential_params_sp(cp, CAR.LANDROVER_DEFENDER_2023)
  interface = CarInterface(cp, cp_sp)
  on = hud(0x30, 3, 1, 82, gap=raw)
  _, state_sp = interface.update(decode_can(1_000_000_000, DEFENDER_CAN0 + [(0x1FB, on, 1)]))
  event = messaging.new_message("carStateSP")
  event.carStateSP = convert_to_capnp(state_sp)
  assert messaging.log_from_bytes(event.to_bytes()).carStateSP.stockCruiseGap == level
  off = hud(0xC0, 6, 2, 82)
  _, state_sp = interface.update(decode_can(1_050_000_000, DEFENDER_CAN0 + [(0x1FB, off, 1)]))
  assert state_sp.stockCruiseGap == 0


def test_defender_can1_hud_and_lkas_button_keep_receive_order(monkeypatch):
  monkeypatch.delenv('LANDROVER_CRUISE_HUD_BENCH', raising=False)
  monkeypatch.setenv('REPLAY', '1')
  cp = CarInterface.get_non_essential_params(CAR.LANDROVER_DEFENDER_2023)
  cp.alternativeExperience |= ALTERNATIVE_EXPERIENCE.ENABLE_MADS
  cp_sp = CarInterface.get_non_essential_params_sp(cp, CAR.LANDROVER_DEFENDER_2023)
  interface = CarInterface(cp, cp_sp)
  button_off = (0x24, bytes(8), 0)
  button_on = (0x24, bytes(7) + b'\x20', 0)
  first_hud = (0x1FB, hud(0xC0, 6, 0), 1)
  interface.update(decode_can(1_000_000_000, [button_off, first_hud, button_on]))
  assert not interface.CS.manual_lkas_on
  next_hud = (0x1FB, hud(0xC0, 6, 1), 1)
  interface.update(decode_can(1_050_000_000, [next_hud, button_off, button_on]))
  assert interface.CS.manual_lkas_on
