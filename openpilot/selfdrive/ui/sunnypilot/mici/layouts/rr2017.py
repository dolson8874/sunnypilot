import json

from opendbc.car.landrover.values import CAR as LANDROVER
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigParamControl
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.sunnypilot.selfdrive.car.sync_sunnylink_params import CAR_LIST_JSON_OUT
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller

RR2017 = LANDROVER.RANGEROVER_VOGUE_2017


class RangeRoverSettingsMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._vehicle = BigButton(tr("vehicle selection"))
    self._vehicle.set_click_callback(self._confirm_vehicle_selection)
    self._mads = BigParamControl(tr("MADS"), "Mads")
    self._rr2017_mads = BigParamControl(tr("Range Rover MADS"), "RR2017Mads",
                                       description=tr("Engage steering with stock ACC. Set the following distance to 4 to disengage steering."))

    for item in (self._vehicle, self._mads, self._rr2017_mads):
      item.set_enabled(ui_state.is_offroad)
    self._mads.set_visible(self._has_rr2017)
    self._rr2017_mads.set_visible(self._has_rr2017)
    self._scroller.add_widgets([self._vehicle, self._mads, self._rr2017_mads])

  @staticmethod
  def _has_rr2017() -> bool:
    bundle = ui_state.params.get("CarPlatformBundle")
    platform = bundle.get("platform") if bundle else getattr(ui_state.CP, "carFingerprint", None)
    return platform == RR2017

  def _refresh(self):
    bundle = ui_state.params.get("CarPlatformBundle")
    self._vehicle.set_value(bundle.get("name", bundle.get("platform", "")) if bundle else tr("automatic"))
    self._mads.refresh()
    self._rr2017_mads.set_checked(bool(ui_state.params.get("RR2017Mads", return_default=True)))

  def show_event(self):
    super().show_event()
    self._refresh()

  def _confirm_vehicle_selection(self):
    bundle = ui_state.params.get("CarPlatformBundle") or {}
    auto = bundle.get("platform") == RR2017
    text = tr("slide to select automatic detection") if auto else tr("slide to select Range Rover 2017")
    icon = gui_app.texture("icons_mici/settings/device/lkas.png", 110, 110)
    gui_app.push_widget(BigConfirmationDialog(text, icon, lambda: self._set_vehicle(auto)))

  def _set_vehicle(self, auto: bool):
    if not ui_state.is_offroad():
      return

    if auto:
      if (ui_state.params.get("CarPlatformBundle") or {}).get("platform") == RR2017:
        ui_state.params.remove("CarPlatformBundle")
    else:
      with open(CAR_LIST_JSON_OUT) as car_list:
        for name, data in json.load(car_list).items():
          if data.get("platform") == RR2017:
            ui_state.params.put("CarPlatformBundle", {**data, "name": name}, block=True)
            break
    self._refresh()
