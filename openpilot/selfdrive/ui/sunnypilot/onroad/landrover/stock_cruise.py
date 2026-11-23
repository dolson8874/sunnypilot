from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.landrover.values import CAR


def stock_cruise_display(ui_state) -> tuple[bool, float] | None:
  if ui_state.CP is None or ui_state.CP.carFingerprint != CAR.RANGEROVER_VOGUE_2017:
    return None

  sm = ui_state.sm
  cruise = sm["carState"].cruiseState
  fresh = sm.alive["carStateSP"] and sm.valid["carStateSP"] and sm.recv_frame["carStateSP"] >= ui_state.started_frame
  speed = sm["carStateSP"].stockCruiseSetSpeedKph if fresh and cruise.enabled else 0.0
  return cruise.available, speed if ui_state.is_metric else speed * CV.KPH_TO_MPH
