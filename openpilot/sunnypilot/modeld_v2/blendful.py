"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import numpy as np

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.sunnypilot.modeld_v2.constants import ModelConstants, PREFERENCE_LEVELS, PREFERENCE_MAX_LEVEL

LANE_WIDTH_DEFAULT = 3.6  # m
LANE_WIDTH_CLIP = (2.8, 4.5)  # m
LOOKAHEAD_TIME = 1.5  # s
MIN_LOOKAHEAD = 10.0  # m
MIN_SPEED = 5.0  # m/s
LINE_STD = (0.2, 0.6)
POINT_STD = 0.1
YIELD = (0.2, 0.45)
X_IDXS = np.array(ModelConstants.X_IDXS)
CENTER_CHECK_X = np.array([15.0, 20.0, 25.0])
CENTER_MIN_LANE_PROB = 0.85
CENTER_DEADBAND = 0.05  # m
CENTER_CONFIRM_FRAMES = round(0.5 / DT_MDL)
CENTER_MAX_LAT_ACCEL = 0.10  # m/s^2, at most one frame of the normal fast release

# Reserve a central corridor for the vehicle and lateral clearance.
# This design envelope is applied to estimated lane geometry, not measured tire position.
PREFERENCE_RESERVED_WIDTH = 2.5  # m
PREFERENCE_MAX_SHIFT = 0.10  # m
PREFERENCE_BUILD_RATE = 0.05  # m/s


class Blendful:
  def __init__(self, guard_lane_center: bool = False, preference: int = 0):
    self.guard_lane_center = guard_lane_center
    self.preference = preference if guard_lane_center and preference in PREFERENCE_LEVELS else 0
    self.preferred_offset = 0.0
    self._offset_level = 0
    self.preference_ready = False
    self.reason = "unknown"
    self.guard_was_enabled = False
    self.center_direction = 0
    self.center_frames = 0
    self.lane_width = FirstOrderFilter(LANE_WIDTH_DEFAULT, 10.0, DT_MDL, initialized=False)
    self.line_gone = FirstOrderFilter(np.zeros(2), 2.0, DT_MDL)
    self.line_probs_slow = FirstOrderFilter(np.zeros(2), 3.0, DT_MDL)
    self.line_probs = FirstOrderFilter(np.zeros(2), 0.5, DT_MDL)
    self.usual_offset = FirstOrderFilter(0.0, 10.0, DT_MDL, initialized=False)
    self.going_around = False
    self.since_turning = 0.0
    self.trust = 0.0
    self.line_trust = 0.0
    self.dk = 0.0 # delta kappa; difference between lane center and model plan
    self.l_prob = 0.0
    self.r_prob = 0.0
    self.model_curvature = 0.0
    self.smooth = 0.0 # smooths the correction target below .53 lat accel
    self.curvature = 0.0

  def update(self, model_output: dict[str, np.ndarray], v_ego: float, active: bool, model_curvature: float, enabled: bool = True) -> float:
    self.preference_ready = False
    self.l_prob = self.r_prob = 0.0
    self.model_curvature = model_curvature
    if not enabled:
      if self.curvature or self.trust or self.guard_was_enabled:
        self.__init__(self.guard_lane_center, self.preference)
      self.reason = "disabled"
      return 0.0
    fading = not active or v_ego < MIN_SPEED
    self.reason = "inactive" if not active else "lowSpeed"
    center_errors = None
    if self.guard_lane_center:
      self.guard_was_enabled = True
      if not fading and np.isfinite(v_ego) and np.isfinite(model_curvature):
        self.reason = "laneGeometry"
        center_errors = self._center_errors(model_output)
      fading = center_errors is None
      if fading:
        self.preferred_offset = 0.0
    if fading:
      self.trust = self.line_trust = 0.0
      self.usual_offset.initialized = False
      self.lane_width.initialized = False
      self.going_around = False
    target = 0.0 if fading else self._target(model_output, v_ego, model_curvature)
    if self.guard_lane_center:
      limit = self._center_limit(center_errors, v_ego)
      lower, upper = min(0.0, limit), max(0.0, limit)
      target = float(np.clip(target, lower, upper))
      self.smooth = float(np.clip(self.smooth, lower, upper))
      if not np.isfinite(v_ego) or not np.isfinite(model_curvature):
        self.reason = "inputInvalid"
        self.curvature = 0.0
        return 0.0
    target = self.smooth = self.smooth + (target - self.smooth) * DT_MDL / (DT_MDL + np.interp(abs(model_curvature) * v_ego ** 2, [0.18, 0.53], [0.5, 0.0]))
    build = 0.5 / max(v_ego, 1.0) ** 2 * DT_MDL  # jerk over 1 second
    release = (0.5 if fading else 2.0) / max(v_ego, 1.0) ** 2 * DT_MDL  # lets go fast, but past zero it builds like any other pull
    k = self.curvature
    self.curvature = float(np.clip(target, max(k - release, -build) if k > 0 else k - build, min(k + release, build) if k < 0 else k + build))
    if self.guard_lane_center:
      # A stored correction can point away from center after the path changes.
      self.curvature = float(np.clip(self.curvature, lower, upper))
    if self.guard_lane_center and self.curvature:
      self.reason = "correcting"
    return self.curvature

  def _center_errors(self, model_output: dict[str, np.ndarray]) -> np.ndarray | None:
    probs = model_output['lane_lines_prob'][0, [3, 5]]
    lines = model_output['lane_lines'][0, 1:3, :, 0]
    stds = model_output['lane_lines_stds'][0, 1:3, :, 0]
    plan = model_output['plan'][0, :, :2]
    if (not np.all(np.isfinite(probs)) or np.any(probs < CENTER_MIN_LANE_PROB) or
        not np.all(np.isfinite(lines)) or not np.all(np.isfinite(stds)) or np.any(stds <= 0) or
        not np.all(np.isfinite(plan)) or np.any(np.diff(plan[:, 0]) < 0) or
        plan[0, 0] > CENTER_CHECK_X[0] or plan[-1, 0] < CENTER_CHECK_X[-1]):
      return None

    left, right = [np.interp(CENTER_CHECK_X, X_IDXS, line) for line in lines]
    width = right - left
    if np.any((width < 2.5) | (width > LANE_WIDTH_CLIP[1])):
      return None
    if any(np.any(np.interp(CENTER_CHECK_X, X_IDXS, std) > LINE_STD[0]) for std in stds):
      return None
    desired = 0.0
    if self.preference or self.preferred_offset:
      spare_half_width = max(0.0, (float(np.min(width)) - PREFERENCE_RESERVED_WIDTH) / 2)
      limit = min(PREFERENCE_MAX_SHIFT, spare_half_width / 3)
      desired = self.preference / PREFERENCE_MAX_LEVEL * limit
      # Honor shrinking lane clearance immediately, even during a setting change.
      previous = self.preferred_offset
      if previous:
        previous_limit = abs(self._offset_level) / PREFERENCE_MAX_LEVEL * limit
        previous = min(previous_limit, max(-previous_limit, previous))
      target = 0.0 if previous * desired < 0.0 else desired
      step = PREFERENCE_BUILD_RATE * DT_MDL
      self.preferred_offset = min(previous + step, max(previous - step, target))
      if self.preferred_offset == desired or abs(self.preferred_offset) > abs(previous):
        self._offset_level = self.preference
    self.preference_ready = self.preferred_offset == desired
    return np.interp(CENTER_CHECK_X, plan[:, 0], plan[:, 1]) - (left + right) / 2 - self.preferred_offset

  def _center_limit(self, errors: np.ndarray | None, v_ego: float) -> float:
    direction = 0
    if errors is not None:
      self.reason = "yielding" if self.going_around else "lineConfidence"
    if errors is not None and min(self.l_prob, self.r_prob) >= CENTER_MIN_LANE_PROB and not self.going_around:
      self.reason = "withinBandOrDisagreement"
      if np.all(errors > CENTER_DEADBAND):
        direction = -1
      elif np.all(errors < -CENTER_DEADBAND):
        direction = 1

    if direction != self.center_direction or not direction:
      self.center_frames = 0
    self.center_direction = direction
    if not direction:
      return 0.0
    self.center_frames = min(self.center_frames + 1, CENTER_CONFIRM_FRAMES)
    self.reason = "confirming"
    if self.center_frames < CENTER_CONFIRM_FRAMES:
      return 0.0

    self.reason = "fitLimited"
    # Approximate the additional displacement by delta_curvature * distance^2 / 2.
    # Stay on the original side of the preferred position at every checked distance.
    max_curvature = min(CENTER_MAX_LAT_ACCEL / v_ego ** 2, float(np.min(2 * np.abs(errors) / CENTER_CHECK_X ** 2)))
    return direction * max_curvature

  def _target(self, model_output: dict[str, np.ndarray], v_ego: float, model_curvature: float) -> float:
    lookahead = max(v_ego * LOOKAHEAD_TIME, MIN_LOOKAHEAD)
    lines = model_output['lane_lines'][0, :, :, 0]
    stds = model_output['lane_lines_stds'][0, :, :, 0]

    lone_weight = np.interp(abs(model_curvature) * v_ego ** 2, [0.18, 0.53], [0.5, 1.0])  # 0.5 on straights, 1.0 in curves
    probs = self.line_probs.update(model_output['lane_lines_prob'][0, 1::2][1:3])
    absent = (probs < 0.3) & (lone_weight > 0.5)
    gone = self.line_gone.update((model_output['lane_lines_prob'][0, 1::2][1:3] < 0.3).astype(float))
    missing = np.where(absent, 1.0, gone)
    dropping = bool(np.any((probs < 0.6 * self.line_probs_slow.update(model_output['lane_lines_prob'][0, 1::2][1:3])) & ~absent))
    l_prob = float(probs[0] * np.interp(np.interp(0.5 * lookahead, X_IDXS, stds[1]), LINE_STD, [1.0, 0.0]))
    r_prob = float(probs[1] * np.interp(np.interp(0.5 * lookahead, X_IDXS, stds[2]), LINE_STD, [1.0, 0.0]))
    self.l_prob, self.r_prob = l_prob, r_prob
    # one line steadily on its own still centers at lone_weight. a line that is disappearing gives control back to laneless
    if missing[1] > 0.8 and l_prob > 0.5:
      lane_trust = l_prob * lone_weight
    elif missing[0] > 0.8 and r_prob > 0.5:
      lane_trust = r_prob * lone_weight
    elif dropping:
      lane_trust = min(l_prob, r_prob)
    else:
      lane_trust = l_prob + r_prob - l_prob * r_prob
    if lone_weight > 0.5 and lane_trust < self.line_trust:
      lane_trust = self.line_trust + (lane_trust - self.line_trust) * DT_MDL / (lone_weight - 0.5 + DT_MDL)
    self.line_trust = lane_trust
    if lane_trust <= 0.0:
      self.trust = 0.0
      return 0.0
    if l_prob + r_prob <= 0.0:  # keep the last fit while trust lets go
      self.trust = min(self.trust, lane_trust)
      return float(self.trust * self.dk)

    win = (X_IDXS >= 0.5 * lookahead) & (X_IDXS <= 1.5 * lookahead)
    x = X_IDXS[win]
    half_width = self.lane_width.x / 2
    if l_prob * r_prob > 0.5:
      width = np.interp(lookahead, X_IDXS, lines[2]) - np.interp(lookahead, X_IDXS, lines[1])
      self.lane_width.update(float(np.clip(width, *LANE_WIDTH_CLIP)))
      half_width = np.clip(lines[2, win] - lines[1, win], *LANE_WIDTH_CLIP) / 2
    l_var = stds[1, win] ** 2 / max(l_prob, 1e-4)
    r_var = stds[2, win] ** 2 / max(r_prob, 1e-4)
    center = (r_var * (lines[1, win] + half_width) + l_var * (lines[2, win] - half_width)) / (l_var + r_var)
    weight = 1.0 / (l_var * r_var / (l_var + r_var) + POINT_STD ** 2)

    # Fit curvature to place the plant in center: e ~ dk x^2 / 2
    plan_x = np.interp(x, model_output['plan'][0, :, 0], model_output['plan'][0, :, 1])
    plan_share = np.interp(abs(model_curvature) * lookahead ** 2 / 2, [0.5, 2.0], [0.3, 0.5]) # up to 50% plan y vs curvature parabola in sharp curves
    error = np.clip(center + self.preferred_offset - ((1 - plan_share) * model_curvature * x ** 2 / 2 + plan_share * plan_x), -1.0, 1.0)
    dk = 2.0 * np.sum(weight * error * x ** 2) / np.sum(weight * x ** 4)

    # A model planning to end up further from its usual spot in the lane than the plant is now is likely going around something
    hw_now = np.clip(lines[2, 0] - lines[1, 0], *LANE_WIDTH_CLIP) / 2 if l_prob * r_prob > 0.5 else self.lane_width.x / 2
    center_now = (l_prob * (lines[1, 0] + hw_now) + r_prob * (lines[2, 0] - hw_now)) / (l_prob + r_prob)
    plan_y = np.interp(lookahead, model_output['plan'][0, :, 0], model_output['plan'][0, :, 1])
    offset = plan_y - np.interp(lookahead, x, center)
    if min(gone) > 0.5:  # both lines gone: turns, intersections, relearn ideal model position
      self.usual_offset.initialized = False
    usual = self.usual_offset.x if self.usual_offset.initialized else offset
    swerve = abs(offset - usual) - 0.25 * abs(model_curvature) * lookahead ** 2 / 2
    away = swerve - abs(-center_now - usual)
    lane_curvature = 2.0 * np.polyfit(x, center, 2)[0]
    inside_curve = abs(lane_curvature) * lookahead ** 2 / 2 > 0.1 and (offset - usual) * lane_curvature > 0
    self.since_turning = 0.0 if abs(model_curvature) * lookahead ** 2 / 2 > 0.5 else self.since_turning + DT_MDL
    if inside_curve:
      self.going_around = False
    elif away > YIELD[0] and self.since_turning > 2.0:
      self.going_around = True
    elif swerve < YIELD[0] / 2:
      self.going_around = False
    self.usual_offset.update_alpha(20.0 if self.going_around else 10.0)
    self.usual_offset.update(offset)

    if inside_curve:
      lane_trust *= np.interp(abs(offset) - abs(center_now) - 0.25 * abs(model_curvature) * lookahead ** 2 / 2, (0.5, 1.0), [1.0, 0.0])
    else:
      lane_trust *= np.interp(swerve, (YIELD[0] / 2, YIELD[0]), [1.0, 0.0]) if self.going_around else np.interp(away, YIELD, [1.0, 0.0])

    if lane_trust < self.trust:
      dk = float(np.clip(dk, min(self.dk, 0.0), max(self.dk, 0.0)))
    self.trust = lane_trust if lane_trust < self.trust else self.trust + (lane_trust - self.trust) * DT_MDL / (1.5 + DT_MDL)
    self.dk = dk
    return float(self.trust * dk)
