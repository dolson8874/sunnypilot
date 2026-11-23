"""Display optional read-only cruise analysis summaries."""
import time
import json
import pyray as rl

from openpilot.cereal import log
from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.onroad.driver_state import BTN_SIZE
from openpilot.selfdrive.ui.sunnypilot.onroad.developer_ui import DeveloperUiState
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight, font_fallback
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.text_measure import measure_text_cached

def indicator_rect(rect, bottom_debug=False, right_debug=False):
  """Reserve the actual bottom debug bar, driver icon and right debug column."""
  scale = 0.5 if rect.height < 700 else 1.0
  margin = 24 * scale
  right_space = 224 if right_debug else 0
  width = min(440 * scale, rect.width - 2 * margin - right_space)
  if width < 160 * scale:
    return None
  driver_space = UI_BORDER_SIZE + BTN_SIZE if scale == 1 else 0
  bottom_space = (61 if bottom_debug else 0) + driver_space
  height = 112 * scale
  y = rect.y + rect.height - bottom_space - 12 * scale - height
  if y < rect.y + margin:
    return None
  return rl.Rectangle(rect.x + margin, y, width, height)


class CruiseAnalysisRenderer(Widget):
  def __init__(self):
    super().__init__()
    self._font = gui_app.font(FontWeight.MEDIUM)
    self._analysis_message_time = -1
    self._analysis_snapshot = {}

  def _render_analysis(self, rect):
    sm = ui_state.sm
    if not ui_state.cruise_analysis_show or sm['selfdriveState'].alertSize != log.SelfdriveState.AlertSize.none:
      return
    developer = ui_state.developer_ui if gui_app.big_ui() and gui_app.sunnypilot_ui() else DeveloperUiState.OFF
    placement = indicator_rect(rect, developer in (DeveloperUiState.BOTTOM, DeveloperUiState.BOTH),
                               developer in (DeveloperUiState.RIGHT, DeveloperUiState.BOTH))
    if placement is None:
      return
    scale = 0.5 if rect.height < 700 else 1.0
    y = placement.y - (166 if scale < 1 else 132) * scale
    if y < rect.y + 24 * scale:
      return
    text = 'Analysis: unavailable'
    if ('cruiseAnalysis' in sm.services and sm.valid['cruiseAnalysis'] and
        sm.recv_frame['cruiseAnalysis'] >= ui_state.started_frame):
      try:
        if self._analysis_message_time != sm.logMonoTime['cruiseAnalysis']:
          self._analysis_snapshot = json.loads(sm['cruiseAnalysis'].snapshotJson)
          self._analysis_message_time = sm.logMonoTime['cruiseAnalysis']
        snapshot = self._analysis_snapshot
        age = time.monotonic() - sm.logMonoTime['cruiseAnalysis'] / 1e9
        frame = snapshot.get('frames', {}).get('0:268:-1', {})
        word = frame.get('values', {}).get('word56Raw')
        if (frame.get('excluded') is not None or
            not 0 <= time.monotonic_ns() - frame.get('eventMonoTime', 0) < frame.get('staleAfterNs', 0)):
          word = None
        status = ('Analysis: stale' if age >= 2 else
                  'Analysis: limited (size budget)' if snapshot.get('snapshotOmitted') else
                  'Analysis: error' if snapshot.get('lastError') else 'Candidate RAW / age')
        slots = sum(bool(slot['memberMask']) for slot in snapshot.get('slots', []))
        counts = snapshot.get('counts', {})
        text = f"{status}\nCAN0 0x10C: {word if word is not None else '?'}\nRadar slots seen: {slots}  Frames: {counts.get('frames', 0)}"
      except (ValueError, KeyError, TypeError):
        text = 'Analysis: decode error'
    box = rl.Rectangle(placement.x, y, placement.width, (160 if scale < 1 else 126) * scale)
    rl.draw_rectangle_rounded(box, 0.2, 8, rl.Color(0, 0, 0, 165))
    font = font_fallback(self._font)
    for i, line in enumerate(text.splitlines()):
      preferred_size = (26 if scale < 1 else 22) * scale
      size = min(preferred_size, preferred_size * (box.width - 24 * scale) / max(1, measure_text_cached(font, line, preferred_size).x))
      rl.draw_text_ex(font, line, rl.Vector2(box.x + 12 * scale, box.y + (8 + 38 * i) * scale),
                      size, 0, rl.Color(255, 210, 80, 255))

  def _render(self, rect):
    self._render_analysis(rect)
