"""Range Rover Vogue 2017 stock ACC display and MADS release input."""

from opendbc.can.parser import CANParser
from opendbc.car import Bus
from opendbc.car.landrover.values import CAR, CanBus, DBC

SET_SPEED_FRAME = 0x284
GAP_FRAME = 0x2F0
GAP_BUTTON_FRAME = 0x2D0
FRESH_NS = 400_000_000  # Ten periods at the 25 Hz specified by the RR source.
GAP_LEVELS = (3, 2, 4, 1)
GAP_LONGEST = GAP_LEVELS.index(4)
GAP_RESPONSE_NS = 1_000_000_000


class RR2017StockCruise:
  def __init__(self, *, mads_gap_release: bool = False):
    self.parser = CANParser(DBC[CAR.RANGEROVER_VOGUE_2017][Bus.pt], [(SET_SPEED_FRAME, 25), (GAP_FRAME, 25)], CanBus.UNDERBODY)

    self.mads_gap_release = mads_gap_release
    self.gap_release_requested = False
    self._last_gap = None
    self._last_gap_ns = 0
    self._last_button_ns = 0
    self._button_pressed = False
    self._gap_press_ns = 0

  def update(self, can_packets, now_ns: int, *, can_valid: bool = True) -> tuple[float, int]:
    self.gap_release_requested = False
    if self.mads_gap_release:
      if can_valid:
        self._update_gap_release(can_packets, now_ns)
      else:
        self._last_gap_ns = self._last_button_ns = self._gap_press_ns = 0
    packets = [(stamp, [frame for frame in frames if frame[0] in (SET_SPEED_FRAME, GAP_FRAME) and
                        frame[2] == CanBus.UNDERBODY and len(frame[1]) == 8]) for stamp, frames in can_packets]
    self.parser.update(packets)
    speed = self._fresh_value(SET_SPEED_FRAME, 'VSetDist', now_ns)
    gap = self._fresh_value(GAP_FRAME, 'GAP', now_ns)
    return (speed if speed is not None else 0.0,
            GAP_LEVELS[int(gap)] if gap is not None else 0)

  def _update_gap_release(self, packets, now_ns: int):
    gap_signal = self.parser.dbc.addr_to_msg[GAP_FRAME].sigs['GAP']
    button_signals = self.parser.dbc.addr_to_msg[GAP_BUTTON_FRAME].sigs

    for stamp, frames in packets:
      if not 0 <= now_ns - stamp < FRESH_NS:
        continue
      # Associate a button and setting value received in the same CAN batch.
      for address in (GAP_BUTTON_FRAME, GAP_FRAME):
        for frame_address, data, bus in frames:
          if frame_address != address or bus != CanBus.UNDERBODY or len(data) != 8:
            continue
          if address == GAP_BUTTON_FRAME:
            pressed = any(button_signals[name].get_raw_value(data) for name in ('GapBtn1', 'GapBtn2'))
            fresh_button = self._last_button_ns and 0 < stamp - self._last_button_ns < FRESH_NS
            if not fresh_button:
              self._gap_press_ns = 0
            elif pressed and not self._button_pressed:
              self._gap_press_ns = stamp
            self._button_pressed = pressed
            self._last_button_ns = stamp
          else:
            gap = gap_signal.get_raw_value(data)
            fresh_gap = self._last_gap_ns and 0 < stamp - self._last_gap_ns < FRESH_NS
            if fresh_gap and gap != self._last_gap:
              button_fresh = 0 <= stamp - self._last_button_ns < FRESH_NS
              pressed_recently = self._gap_press_ns and 0 <= stamp - self._gap_press_ns <= GAP_RESPONSE_NS
              if gap == GAP_LONGEST and button_fresh and pressed_recently:
                self.gap_release_requested = True
              self._gap_press_ns = 0
            elif not fresh_gap:
              self._gap_press_ns = 0
            self._last_gap = gap
            self._last_gap_ns = stamp

  def _fresh_value(self, address: int, signal: str, now_ns: int) -> float | None:
    received = self.parser.ts_nanos[address][signal]
    if received and 0 <= now_ns - received < FRESH_NS:
      return self.parser.vl[address][signal]
    return None
