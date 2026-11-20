from openpilot.selfdrive.ui.ui_state import ui_state


def stock_cruise_gap() -> int:
  sm = ui_state.sm
  if (ui_state.has_longitudinal_control or not sm.alive.get("carStateSP", False) or not sm.valid["carStateSP"]
      or sm.recv_frame["carStateSP"] < ui_state.started_frame):
    return 0

  level = sm["carStateSP"].stockCruiseGap
  return level if 1 <= level <= 4 else 0
