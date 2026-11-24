from types import SimpleNamespace

from openpilot.selfdrive.ui.mici.layouts import main
from openpilot.selfdrive.ui.sunnypilot.mici.layouts import models
from openpilot.system.ui.lib.application import GuiApplication


def make_navigation(monkeypatch):
  clock = SimpleNamespace(now=100.0)
  state = SimpleNamespace(started=True, sm={"carState": SimpleNamespace(standstill=True)})
  page = SimpleNamespace(enabled=True, is_dismissing=False, _return_at=None, _level=0,
                         RETURN_DELAY=models.LanePreferencePage.RETURN_DELAY)
  page.drive_return_due = lambda: models.LanePreferencePage.drive_return_due(page)
  page.cancel_drive_return = lambda: models.LanePreferencePage.cancel_drive_return(page)
  scrolls = []
  layout = SimpleNamespace(_onboarding_window=object(), _settings_layout=SimpleNamespace(lane_preference_page=page),
                           _prev_onroad=True, _prev_standstill=True, _onroad_time_delay=None,
                           _home_layout="home", _onroad_layout="road", _scroll_to=scrolls.append)
  app = SimpleNamespace(_nav_stack=[layout, object(), page], sunnypilot_ui=lambda: True)
  app.widget_in_stack = lambda widget: any(item is widget for item in app._nav_stack)
  app.pop_widget = app._nav_stack.pop
  app.pop_widgets_to = lambda *args, **kwargs: GuiApplication.pop_widgets_to(app, *args, **kwargs)
  gate = SimpleNamespace(allowed=True)
  monkeypatch.setattr(main, "gui_app", app)
  monkeypatch.setattr(main, "ui_state", state)
  monkeypatch.setattr(main, "lane_preference_edit_allowed", lambda: gate.allowed, raising=False)
  monkeypatch.setattr(models, "ui_state", SimpleNamespace(is_onroad=lambda: state.started))
  monkeypatch.setattr(models, "time", SimpleNamespace(monotonic=lambda: clock.now))
  monkeypatch.setattr(models, "save_lane_preference", lambda level, allow_onroad: gate.allowed and abs(level) <= 10 and allow_onroad)
  return clock, state, page, layout, app, gate, scrolls


def test_repeated_saves_restart_the_return_timer(monkeypatch):
  clock, _, page, layout, app, _, scrolls = make_navigation(monkeypatch)
  models.LanePreferencePage._select(page, -1)
  clock.now += 2
  models.LanePreferencePage._select(page, -2)
  models.LanePreferencePage._select(page, -11)
  assert page._level == -2

  clock.now += 2.9
  main.MiciMainLayout._handle_transitions(layout)
  assert app._nav_stack[-1] is page and not scrolls
  clock.now += 0.1
  main.MiciMainLayout._handle_transitions(layout)
  assert app._nav_stack == [layout] and scrolls == ["road"]
  assert page._return_at is None


def test_done_and_blocked_edit_close_nested_settings(monkeypatch):
  for close_with_done in (True, False):
    _, _, page, layout, app, gate, scrolls = make_navigation(monkeypatch)
    if close_with_done:
      models.LanePreferencePage._finish(page)
    else:
      gate.allowed = False

    main.MiciMainLayout._handle_transitions(layout)
    assert app._nav_stack == [layout] and scrolls == ["road"]


def test_offroad_transition_cancels_the_pending_return(monkeypatch):
  clock, state, page, layout, app, _, scrolls = make_navigation(monkeypatch)
  models.LanePreferencePage._select(page, -1)
  layout._onroad_time_delay = 0
  state.started = False
  state.sm["carState"].standstill = False
  clock.now += 4
  main.MiciMainLayout._handle_transitions(layout)
  assert page._return_at is None and layout._onroad_time_delay is None
  assert app._nav_stack[-1] is page and scrolls == ["home"]
