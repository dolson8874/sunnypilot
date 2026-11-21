import math
import time

from openpilot.common.realtime import DT_MDL


def maneuver_message_fresh(sm, service):
  """Allow three model periods between the publisher and the consuming tick."""
  if not sm.seen[service]:
    return False
  now = time.monotonic_ns()
  age_limit = round(3 * DT_MDL * 1e9)
  return (0 <= now - round(sm.recv_time[service] * 1e9) < age_limit and
          0 <= now - sm.logMonoTime[service] < age_limit)


def select_lateral_plan(sm, params, active, current_curvature):
  service = 'lateralManeuverPlan'
  if not active:
    return current_curvature, 0
  if (sm.valid[service] and maneuver_message_fresh(sm, service) and
      math.isfinite(sm[service].desiredCurvature) and params.get_bool('LateralManeuverMode')):
    return sm[service].desiredCurvature, sm.logMonoTime[service]
  if sm.seen[service] and not (sm.valid['modelV2'] and sm.alive['modelV2']):
    return current_curvature, 0
  return sm['modelV2'].action.desiredCurvature, sm.logMonoTime['modelV2']
