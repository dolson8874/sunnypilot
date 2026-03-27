import math

import numpy as np
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.common.params import Params

TRAJECTORY_SIZE = 33
CAMERA_OFFSET = 0.0


def clamp(num, min_value, max_value):
  if min_value > num > max_value:
    return (min_value + max_value) * 0.5
  if num < min_value:
    return min_value
  if num > max_value:
    return max_value
  return num


def lerp(start, end, t):
  t = clamp(t, 0.0, 1.0)
  return (start * (1.0 - t)) + (end * t)


class LanePlanner:
  def __init__(self):
    self.ll_t = np.zeros((TRAJECTORY_SIZE,))
    self.ll_x = np.zeros((TRAJECTORY_SIZE,))
    self.lll_y = np.zeros((TRAJECTORY_SIZE,))
    self.rll_y = np.zeros((TRAJECTORY_SIZE,))
    self.le_y = np.zeros((TRAJECTORY_SIZE,))
    self.re_y = np.zeros((TRAJECTORY_SIZE,))

    self.lane_width_estimate = FirstOrderFilter(3.2, 3.0, DT_MDL)
    self.lane_width = 3.2
    self.lane_width_last = self.lane_width
    self.lane_change_multiplier = 1.0

    self.lll_prob = 0.0
    self.rll_prob = 0.0
    self.d_prob = 0.0

    self.lll_std = 0.0
    self.rll_std = 0.0

    self.l_lane_change_prob = 0.0
    self.r_lane_change_prob = 0.0

    self.lane_width_left = 0.0
    self.lane_width_right = 0.0
    self.lane_width_left_filtered = FirstOrderFilter(1.0, 1.0, DT_MDL)
    self.lane_width_right_filtered = FirstOrderFilter(1.0, 1.0, DT_MDL)
    self.lane_offset_filtered = FirstOrderFilter(0.0, 2.0, DT_MDL)

    self.lanefull_mode = False
    self.d_prob_count = 0
    self.offset_total = 0.0

    self.params = Params()

  def parse_model(self, md):
    lane_lines = md.laneLines
    edges = md.roadEdges

    if len(lane_lines) >= 4 and len(lane_lines[0].t) == TRAJECTORY_SIZE:
      self.ll_t = (np.array(lane_lines[1].t) + np.array(lane_lines[2].t)) / 2
      self.ll_x = lane_lines[1].x
      self.lll_y = np.array(lane_lines[1].y)
      self.rll_y = np.array(lane_lines[2].y)
      self.lll_prob = md.laneLineProbs[1]
      self.rll_prob = md.laneLineProbs[2]
      self.lll_std = md.laneLineStds[1]
      self.rll_std = md.laneLineStds[2]

      self.lane_width_left = float(np.mean(np.abs(np.array(lane_lines[1].y) - np.array(lane_lines[0].y))))
      self.lane_width_right = float(np.mean(np.abs(np.array(lane_lines[3].y) - np.array(lane_lines[2].y))))

    if len(edges) >= 2 and len(edges[0].t) == TRAJECTORY_SIZE:
      self.le_y = np.array(edges[0].y) + md.roadEdgeStds[0] * 0.4
      self.re_y = np.array(edges[1].y) - md.roadEdgeStds[1] * 0.4
    else:
      self.le_y = self.lll_y
      self.re_y = self.rll_y

  def get_d_path(self, v_ego, path_t, path_xyz, curve_speed=0.0):
    l_prob, r_prob = self.lll_prob, self.rll_prob
    width_pts = self.rll_y - self.lll_y
    prob_mods = []
    for t_check in (0.0, 1.5, 3.0):
      width_at_t = np.interp(t_check * (v_ego + 7.0), self.ll_x, width_pts)
      prob_mods.append(np.interp(width_at_t, [4.5, 6.0], [1.0, 0.0]))
    mod = min(prob_mods) if len(prob_mods) > 0 else 1.0
    l_prob *= mod
    r_prob *= mod

    l_std_mod = np.interp(self.lll_std, [0.15, 0.3], [1.0, 0.0])
    r_std_mod = np.interp(self.rll_std, [0.15, 0.3], [1.0, 0.0])
    l_prob *= l_std_mod
    r_prob *= r_std_mod

    current_lane_width = abs(self.rll_y[0] - self.lll_y[0])
    both_lane_available = False
    if l_prob > 0.5 and r_prob > 0.5 and self.lane_change_multiplier > 0.5:
      both_lane_available = True
      self.lane_width_estimate.update(current_lane_width)
      self.lane_width_last = self.lane_width_estimate.x
    else:
      self.lane_width_estimate.update(self.lane_width_last)

    self.lane_width = self.lane_width_estimate.x
    clipped_lane_width = min(4.0, self.lane_width)
    path_from_left_lane = self.lll_y + clipped_lane_width / 2.0
    path_from_right_lane = self.rll_y - clipped_lane_width / 2.0

    self.d_prob = max(l_prob, r_prob) if not both_lane_available else 1.0

    if self.lane_width_left > 0:
      self.lane_width_left_filtered.update(self.lane_width_left)
    if self.lane_width_right > 0:
      self.lane_width_right_filtered.update(self.lane_width_right)

    adjust_lane_offset = float(self.params.get("AdjustLaneOffset", return_default=True)) * 0.01
    adjust_curve_offset = adjust_lane_offset
    adjust_limit = 0.4

    offset_curve = np.interp(abs(curve_speed), [50, 200], [adjust_curve_offset, 0.0]) * np.sign(curve_speed)

    if self.lane_width_left_filtered.x > 2.2 and self.lane_width_right_filtered.x > 2.2:
      offset_lane = 0.0
    elif self.lane_width_left_filtered.x < 2.0 and self.lane_width_right_filtered.x < 2.0:
      offset_lane = 0.0
    elif self.lane_width_left_filtered.x > self.lane_width_right_filtered.x:
      offset_lane = np.interp(self.lane_width, [2.5, 2.9], [0.0, adjust_lane_offset])
    else:
      offset_lane = np.interp(self.lane_width, [2.5, 2.9], [0.0, -adjust_lane_offset])

    if self.lane_width < 2.5:
      if r_prob > 0.5 and self.lane_width_right_filtered.x < self.lane_width_left_filtered.x:
        lane_path_y = path_from_right_lane
      elif l_prob > 0.5 and self.lane_width_left_filtered.x < 2.0:
        lane_path_y = path_from_left_lane
      else:
        lane_path_y = path_from_left_lane if l_prob > 0.5 or l_prob > r_prob else path_from_right_lane
    elif l_prob > 0.7 and r_prob > 0.7:
      lane_path_y = (path_from_left_lane + path_from_right_lane) / 2.0
    else:
      lane_path_y = (l_prob * path_from_left_lane + r_prob * path_from_right_lane) / (l_prob + r_prob + 1e-4)

    if offset_curve * offset_lane < 0:
      offset_total = np.clip(offset_curve + offset_lane, -adjust_limit, adjust_limit)
    else:
      offset_total = np.clip(max(offset_curve, offset_lane, key=abs), -adjust_limit, adjust_limit)

    self.d_prob *= self.lane_change_multiplier
    if self.lane_change_multiplier >= 0.5:
      self.lane_offset_filtered.update(np.interp(self.d_prob, [0.0, 0.3], [0.0, offset_total]))

    self.d_prob *= np.interp(v_ego * 3.6, [5.0, 10.0], [0.0, 1.0])

    adjust_lane_time = 0.04
    laneline_active = False
    self.d_prob_count = self.d_prob_count + 1 if self.d_prob > 0.3 else 0
    if self.lanefull_mode and self.d_prob_count > int(1 / DT_MDL):
      laneline_active = True
      safe_idxs = np.isfinite(self.ll_t)
      if safe_idxs[0]:
        lane_path_y_interp = np.interp(path_t * (1.0 + adjust_lane_time), self.ll_t[safe_idxs], lane_path_y[safe_idxs])
        path_xyz[:, 1] = self.d_prob * lane_path_y_interp + (1.0 - self.d_prob) * path_xyz[:, 1]

    path_xyz[:, 1] += CAMERA_OFFSET + self.lane_offset_filtered.x
    self.offset_total = self.lane_offset_filtered.x
    return path_xyz, laneline_active
