import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached


def draw_stock_cruise_gap(font: rl.Font, center_x: float, top: float, font_size: int) -> None:
  sm = ui_state.sm
  if not (sm.alive["carStateSP"] and sm.valid["carStateSP"] and sm.recv_frame["carStateSP"] >= ui_state.started_frame):
    return

  level = sm["carStateSP"].stockCruiseGap
  if not 1 <= level <= 4:
    return

  text = tr("Stock GAP {}").format(level)
  size = measure_text_cached(font, text, font_size)
  rect = rl.Rectangle(center_x - size.x / 2 - 10, top, size.x + 20, size.y + 8)
  rl.draw_rectangle_rounded(rect, 0.5, 8, rl.Color(0, 0, 0, 166))
  rl.draw_text_ex(font, text, rl.Vector2(center_x - size.x / 2, top + 4), font_size, 0, rl.WHITE)
