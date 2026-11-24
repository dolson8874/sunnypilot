from types import SimpleNamespace

import pytest

from openpilot.common.params import Params
from openpilot.selfdrive.car import card


@pytest.mark.parametrize("requested", [False, True])
def test_obd_callback_waits_for_matching_panda_mode(tmp_path, monkeypatch, requested):
  params = Params(str(tmp_path))
  params.put_bool("ObdMultiplexingEnabled", not requested, block=True)
  params.put_bool("ObdMultiplexingApplied", not requested, block=True)
  waits = []

  def sleep(_):
    waits.append(params.get("ObdMultiplexingApplied"))
    assert params.get("ObdMultiplexingEnabled") == requested
    # A reconnect can acknowledge the previous mode before it applies the new request.
    params.put_bool("ObdMultiplexingApplied", requested if len(waits) == 2 else not requested, block=True)

  monkeypatch.setattr(card, "time", SimpleNamespace(monotonic=lambda: 0.0, sleep=sleep))
  card.obd_callback(params)(requested)
  assert waits == [None, not requested]


def test_obd_callback_rejects_unconfirmed_existing_request(tmp_path, monkeypatch):
  params = Params(str(tmp_path))
  params.put_bool("ObdMultiplexingEnabled", False, block=True)
  times = iter((0.0, 11.0))
  monkeypatch.setattr(card, "time", SimpleNamespace(monotonic=lambda: next(times)))

  with pytest.raises(TimeoutError, match="did not confirm"):
    card.obd_callback(params)(False)
  assert params.get("FirmwareQueryDone") is None
