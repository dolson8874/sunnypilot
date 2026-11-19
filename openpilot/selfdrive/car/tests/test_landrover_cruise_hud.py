from openpilot.cereal import messaging
from openpilot.selfdrive.pandad import can_capnp_to_list
from opendbc.car.landrover.interface import CarInterface
from opendbc.car.landrover.landrovercan import defender_crc
from opendbc.car.landrover.values import CAR, LandroverFlags


def decode_can(timestamp_ns, frames):
  event = messaging.new_message('can', size=len(frames), logMonoTime=timestamp_ns)
  for msg, (address, data, bus) in zip(event.can, frames, strict=True):
    msg.address, msg.dat, msg.src = address, data, bus
  return can_capnp_to_list([event.to_bytes()])


def hud(flags, mode, counter):
  payload = bytes([flags | counter, mode, 0, 0, 0, 0, 0])
  return bytes([defender_crc(payload[:4])]) + payload


def test_defender_cruise_hud_accepts_card_can_batches(monkeypatch):
  monkeypatch.delenv('LANDROVER_CRUISE_HUD_BENCH', raising=False)
  monkeypatch.setenv('REPLAY', '1')
  cp = CarInterface.get_non_essential_params(CAR.LANDROVER_DEFENDER_2023)
  cp_sp = CarInterface.get_non_essential_params_sp(cp, CAR.LANDROVER_DEFENDER_2023)
  assert cp.flags & LandroverFlags.CRUISE_HUD_BENCH
  interface = CarInterface(cp, cp_sp)
  normal_can = [(0x56, bytes(8), 0), (0x56, bytes(8), 2)]

  state, _ = interface.update(decode_can(1_000_000_000, normal_can))
  assert not state.cruiseState.enabled
  assert state.blockPcmEnable

  off, on = hud(0x80, 0, 0), hud(0x30, 3, 1)
  state, _ = interface.update(decode_can(1_050_000_000, normal_can + [(0x1FB, off, 1)]))
  assert not state.cruiseState.enabled
  state, _ = interface.update(decode_can(1_100_000_000, normal_can + [(0x1FB, on, 0)]))
  assert not state.cruiseState.enabled
  state, _ = interface.update(decode_can(1_150_000_000, normal_can + [(0x1FB, on, 1)]))
  assert state.cruiseState.enabled
  assert not state.blockPcmEnable
