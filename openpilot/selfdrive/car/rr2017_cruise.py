"""Range Rover Vogue 2017 stock ACC display and MADS release input."""

from opendbc.can.parser import CANParser
from opendbc.car import Bus
from opendbc.car.landrover.values import CAR, CanBus, DBC

SET_SPEED_FRAME = 0x284
GAP_FRAME = 0x2F0
ACC_STATE_FRAME = 0x156
CANCEL_FRAME = 0x2D0
FRESH_NS = 400_000_000  # Ten periods at the 25 Hz specified by the RR source.
GAP_LEVELS = (3, 2, 4, 1)
# Match the RR2017 Panda safety hook. ACC OFF must predate the CANCEL press.
ACC_FRESH_NS = 100_000_000
ACC_OFF_CONFIRM_NS = 100_000_000


class RR2017StockCruise:
  def __init__(self, *, mads_cancel_release: bool = False):
    self.parser = CANParser(DBC[CAR.RANGEROVER_VOGUE_2017][Bus.pt], [(SET_SPEED_FRAME, 25), (GAP_FRAME, 25)], CanBus.UNDERBODY)

    self.mads_cancel_release = mads_cancel_release
    self.lkas_release_requested = False
    self._acc_on = self.parser.dbc.addr_to_msg[ACC_STATE_FRAME].sigs['CRUISE_ON']
    self._cancel_pressed = self.parser.dbc.addr_to_msg[CANCEL_FRAME].sigs['CruiseCancelRequestCandidate']
    self._last_acc_ns = None
    self._acc_off_since_ns = None
    self._last_button_ns = None
    self._cancel_armed = False

  def update(self, can_packets, now_ns: int, *, can_valid: bool = True) -> tuple[float, int]:
    self.lkas_release_requested = False
    if self.mads_cancel_release:
      if can_valid:
        self._update_cancel_release(can_packets, now_ns)
      else:
        self._last_acc_ns = self._acc_off_since_ns = self._last_button_ns = None
        self._cancel_armed = False
    packets = [(stamp, [frame for frame in frames if frame[0] in (SET_SPEED_FRAME, GAP_FRAME) and
                        frame[2] == CanBus.UNDERBODY and len(frame[1]) == 8]) for stamp, frames in can_packets]
    self.parser.update(packets)
    speed = self._fresh_value(SET_SPEED_FRAME, 'VSetDist', now_ns)
    gap = self._fresh_value(GAP_FRAME, 'GAP', now_ns)
    return (speed if speed is not None else 0.0,
            GAP_LEVELS[int(gap)] if gap is not None else 0)

  def _update_cancel_release(self, packets, now_ns: int):
    for stamp, frames in packets:
      if not 0 <= now_ns - stamp < FRESH_NS:
        continue
      for address, data, bus in frames:
        if bus != CanBus.UNDERBODY or len(data) != 8:
          continue

        if address == ACC_STATE_FRAME:
          if now_ns - stamp > ACC_FRESH_NS:
            continue
          if self._acc_on.get_raw_value(data):
            self._acc_off_since_ns = None
          elif (self._acc_off_since_ns is None or self._last_acc_ns is None or
                not 0 <= stamp - self._last_acc_ns <= ACC_FRESH_NS):
            self._acc_off_since_ns = stamp
          self._last_acc_ns = stamp
        elif address == CANCEL_FRAME:
          if self._last_button_ns is None or not 0 <= stamp - self._last_button_ns < FRESH_NS:
            self._cancel_armed = False
          self._last_button_ns = stamp
          if not self._cancel_pressed.get_raw_value(data):
            self._cancel_armed = True
          elif self._cancel_armed:
            self._cancel_armed = False
            # A press that cancels an active ACC session cannot also cancel MADS.
            if (self._last_acc_ns is not None and 0 <= stamp - self._last_acc_ns <= ACC_FRESH_NS and
                self._acc_off_since_ns is not None and stamp - self._acc_off_since_ns >= ACC_OFF_CONFIRM_NS):
              self.lkas_release_requested = True

  def _fresh_value(self, address: int, signal: str, now_ns: int) -> float | None:
    received = self.parser.ts_nanos[address][signal]
    if received and 0 <= now_ns - received < FRESH_NS:
      return self.parser.vl[address][signal]
    return None
