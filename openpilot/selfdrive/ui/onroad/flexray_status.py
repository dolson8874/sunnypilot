"""Optional receive indicator, independent of engagement and logging control."""
import time
import json
import pyray as rl

from openpilot.cereal import log
from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.onroad.driver_state import BTN_SIZE
from openpilot.selfdrive.ui.onroad.alert_renderer import ALERT_HEIGHTS
from openpilot.selfdrive.ui.sunnypilot.onroad.developer_ui import DeveloperUiState
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.flexray_logd.status import display_state
from openpilot.system.ui.lib.application import gui_app, FontWeight, font_fallback
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.text_measure import measure_text_cached

LABELS = {
  'receiving': tr_noop('Receiving data'),
  'buffering': tr_noop('Preparing recording'),
  'waiting': tr_noop('Waiting for data'),
  'starting': tr_noop('Starting'),
  'retrying': tr_noop('Retrying connection'),
  'stopped': tr_noop('Stopped'),
  'disabled': tr_noop('Logging disabled'),
  'unavailable': tr_noop('Status unavailable'),
}
COLORS = {
  'receiving': rl.Color(100, 230, 140, 255),
  'buffering': rl.Color(255, 210, 80, 255),
  'waiting': rl.Color(255, 210, 80, 255),
  'starting': rl.Color(160, 200, 255, 255),
  'retrying': rl.Color(255, 120, 110, 255),
  'stopped': rl.Color(180, 180, 180, 255),
  'disabled': rl.Color(180, 180, 180, 255),
  'unavailable': rl.Color(255, 160, 100, 255),
}


def indicator_rect(rect, bottom_debug=False, right_debug=False, alert_height=0):
  """Reserve the actual bottom debug bar, driver icon and right debug column."""
  scale = 0.5 if rect.height < 700 else 1.0
  margin = 24 * scale
  right_space = 224 if right_debug else 0
  width = min(440 * scale, rect.width - 2 * margin - right_space)
  if width < 160 * scale:
    return None
  driver_space = UI_BORDER_SIZE + BTN_SIZE if scale == 1 else 0
  bottom_space = max((61 if bottom_debug else 0) + driver_space, alert_height)
  height = 112 * scale
  y = rect.y + rect.height - bottom_space - 12 * scale - height
  if y < rect.y + margin:
    return None
  return rl.Rectangle(rect.x + margin, y, width, height)


class FlexrayStatusRenderer(Widget):
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
        values = {}
        for frame in snapshot['frames'].values():
          if frame['excluded'] is None:
            for name, value in frame['values'].items():
              frame_age = time.monotonic() - frame['eventMonoTime'] / 1e9
              state = 'clock?' if frame_age < 0 else 'stale ' if frame_age * 1e9 >= frame.get('staleAfterNs', 0) else ''
              values[name] = f"{value}({state}{frame_age:.1f}s)"
        text = ('Analysis: stale' if age >= 2 else 'Candidate RAW / age') + '\n'
        text += 'H ' + values.get('hRaw', '?') + ' E ' + values.get('eRaw', '?')
        text += ('\n' if scale < 1 else ' ') + 'DADC ' + values.get('dadcRaw16', '?')
        text += '\nGAP ' + values.get('gapRaw', '?') + ' Icon ' + values.get('iconRaw', '?')
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
    if not ui_state.flexray_show_status or ui_state.sm['selfdriveState'].alertSize == log.SelfdriveState.AlertSize.full:
      return
    font = font_fallback(self._font)
    sm = ui_state.sm
    fresh_trip = sm.recv_frame['flexrayStatus'] >= ui_state.started_frame and sm.valid['flexrayStatus']
    status = sm['flexrayStatus'] if fresh_trip else None
    received_at = sm.logMonoTime['flexrayStatus'] / 1e9 if fresh_trip else None
    state = display_state(status, time.monotonic(), ui_state.flexray_logging_enabled, received_at)
    detail = tr('Waiting for valid frames')
    if state == 'receiving':
      detail = f'4: {status.src4Rate:.0f}/s   6: {status.src6Rate:.0f}/s'
    elif state == 'buffering':
      detail = tr('Buffered: {} frames').format(status.startupBufferedFrames)
    elif state == 'retrying':
      detail = tr('Retry {}').format(status.retryCount)
    elif state in ('disabled', 'stopped', 'unavailable'):
      detail = tr(LABELS[state])
    scale = 0.5 if rect.height < 700 else 1.0
    developer = ui_state.developer_ui if gui_app.big_ui() and gui_app.sunnypilot_ui() else DeveloperUiState.OFF
    placement = indicator_rect(
      rect, developer in (DeveloperUiState.BOTTOM, DeveloperUiState.BOTH),
      developer in (DeveloperUiState.RIGHT, DeveloperUiState.BOTH),
      ALERT_HEIGHTS.get(sm['selfdriveState'].alertSize, 0))
    if placement is None:
      return
    x, y, width = placement.x, placement.y, placement.width
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, width, 112 * scale), 0.2, 8, rl.Color(0, 0, 0, 165))
    rl.draw_circle(int(x + 22 * scale), int(y + 29 * scale), 7 * scale, COLORS[state])
    title = 'FlexRay: ' + tr(LABELS[state])
    text_width = measure_text_cached(font, title, 30 * scale).x
    title_size = min(30 * scale, 30 * scale * (width - 56 * scale) / max(1, text_width))
    rl.draw_text_ex(font, title, rl.Vector2(x + 40 * scale, y + 12 * scale), title_size, 0, COLORS[state])
    detail_width = measure_text_cached(font, detail, 27 * scale).x
    detail_size = min(27 * scale, 27 * scale * (width - 40 * scale) / max(1, detail_width))
    rl.draw_text_ex(font, detail, rl.Vector2(x + 20 * scale, y + 64 * scale), detail_size, 0, rl.Color(240, 240, 240, 255))
