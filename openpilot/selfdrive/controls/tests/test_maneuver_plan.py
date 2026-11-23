from unittest.mock import Mock, patch

import pytest

from openpilot.cereal import messaging
from openpilot.selfdrive.controls.lib.maneuver_plan import maneuver_message_fresh, select_lateral_plan

SERVICE = 'lateralManeuverPlan'
START = 10_000_000_000


def publish(sm, timestamp, received, valid=True, curvature=0.001):
  msg = messaging.new_message(SERVICE, logMonoTime=timestamp, valid=valid)
  msg.lateralManeuverPlan.desiredCurvature = curvature
  sm.update_msgs(received / 1e9, [msg])


def test_expiry_and_restart():
  sm = messaging.SubMaster([SERVICE, 'modelV2'])
  params = Mock()
  params.get_bool.return_value = True
  with patch('time.monotonic_ns') as now:
    now.return_value = START
    assert select_lateral_plan(sm, params, True, 0.) == (0., 0)
    for tick in range(5):
      ts = START + tick * 50_000_000
      now.return_value = ts
      publish(sm, ts, ts)
      assert select_lateral_plan(sm, params, True, 0.) == (sm[SERVICE].desiredCurvature, sm.logMonoTime[SERVICE])
    now.return_value = ts + 149_999_999
    sm.update_msgs(now.return_value / 1e9, [])
    assert select_lateral_plan(sm, params, True, 0.) == (sm[SERVICE].desiredCurvature, sm.logMonoTime[SERVICE])
    now.return_value += 1
    assert select_lateral_plan(sm, params, True, 0.) == (0., 0)
    assert sm.valid[SERVICE] and sm.alive[SERVICE]
    publish(sm, now.return_value, now.return_value)
    assert select_lateral_plan(sm, params, True, 0.) == (sm[SERVICE].desiredCurvature, sm.logMonoTime[SERVICE])
    params.get_bool.return_value = False
    assert select_lateral_plan(sm, params, True, 0.) == (0., 0)


@pytest.mark.parametrize('generated,received,valid,curvature,fresh', [
  (-200_000_000, 0, True, 0., False), (1, 0, True, 0., False),
  (0, -200_000_000, True, 0., False), (0, 1, True, 0., False),
  (0, 0, False, 0., True), (0, 0, True, float('nan'), True), (0, 0, True, float('inf'), True),
])
def test_rejected_commands(generated, received, valid, curvature, fresh):
  sm = messaging.SubMaster([SERVICE, 'modelV2'])
  publish(sm, START + generated, START + received, valid, curvature)
  with patch('time.monotonic_ns', return_value=START):
    assert maneuver_message_fresh(sm, SERVICE) == fresh
    assert select_lateral_plan(sm, Mock(), True, 0.1) == (0.1, 0)


def test_source_switch_with_model_and_inactive_control():
  sm = messaging.SubMaster([SERVICE, 'modelV2'])
  params = Mock()
  params.get_bool.return_value = True
  model = messaging.new_message('modelV2', valid=True, logMonoTime=START)
  model.modelV2.action.desiredCurvature = -.001
  publish(sm, START, START)
  with patch('time.monotonic_ns', return_value=START):
    assert select_lateral_plan(sm, params, False, .02) == (.02, 0)
  with patch('time.monotonic_ns', return_value=START + 160_000_000):
    model.logMonoTime = START + 155_000_000
    sm.update_msgs((START + 160_000_000) / 1e9, [model])
    assert select_lateral_plan(sm, params, True, .02) == (sm['modelV2'].action.desiredCurvature, model.logMonoTime)
