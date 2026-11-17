from types import SimpleNamespace
import json
import time

import pytest

from openpilot.cereal import log
from openpilot.selfdrive.ui.onroad import flexray_status as ui


@pytest.mark.parametrize('size', [(2160, 1080), (1280, 640)])
@pytest.mark.parametrize('alert', ['none', 'small', 'mid', 'full'])
def test_display_geometry_and_alert_suppression(monkeypatch, size, alert):
  draws = []
  now = time.monotonic_ns()

  class SM:
    services = ['cruiseAnalysis']
    valid = {'cruiseAnalysis': True}
    recv_frame = {'cruiseAnalysis': 2}
    logMonoTime = {'cruiseAnalysis': now}

    def __getitem__(self, key):
      if key == 'selfdriveState':
        return SimpleNamespace(alertSize=getattr(log.SelfdriveState.AlertSize, alert))
      return SimpleNamespace(snapshotJson=json.dumps({'frames': {'test': {
        'excluded': None, 'eventMonoTime': now, 'staleAfterNs': 500000000,
        'values': {'hRaw': 0, 'eRaw': 0, 'gapRaw': 0, 'iconRaw': 0, 'dadcRaw16': 0}}}}))

  monkeypatch.setattr(ui.ui_state, 'sm', SM())
  monkeypatch.setattr(ui.ui_state, 'started_frame', 0)
  monkeypatch.setattr(ui.ui_state, 'cruise_analysis_show', False)
  monkeypatch.setattr(ui.gui_app, 'big_ui', lambda: False)
  monkeypatch.setattr(ui, 'font_fallback', lambda _: None)
  monkeypatch.setattr(ui, 'measure_text_cached', lambda *args: SimpleNamespace(x=100))
  monkeypatch.setattr(ui.rl, 'draw_rectangle_rounded', lambda rect, *args: draws.append(rect))
  monkeypatch.setattr(ui.rl, 'draw_text_ex', lambda *args: None)
  renderer = ui.FlexrayStatusRenderer.__new__(ui.FlexrayStatusRenderer)
  renderer._font = None
  renderer._analysis_message_time = -1
  renderer._analysis_snapshot = {}
  rect = ui.rl.Rectangle(0, 0, *size)
  renderer._render_analysis(rect)
  assert not draws
  monkeypatch.setattr(ui.ui_state, 'cruise_analysis_show', True)
  renderer._render_analysis(rect)
  if alert != 'none':
    assert not draws
  else:
    assert len(draws) == 1
    box = draws[0]
    reserved = ui.indicator_rect(rect)
    assert box.x >= 0 and box.y >= 0
    assert box.x + box.width <= size[0]
    assert box.y + box.height < reserved.y
