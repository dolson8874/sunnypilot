"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import numpy as np

from openpilot.common.realtime import DT_MDL
from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.modeld_v2.blendful import Blendful
from openpilot.sunnypilot.modeld_v2.constants import ModelConstants

X = np.array(ModelConstants.X_IDXS)
BUILD, RELEASE = 0.5, 2.0


def frame(center=0.0, plan=0.0, k=0.0, probs=(0.9, 0.9), stds=(0.1, 0.1), width=3.5):
  road = k * X ** 2 / 2
  lines = np.zeros((1, 4, 33, 2))
  lane_stds = np.ones((1, 4, 33, 2))
  for i, off in enumerate((-1.5 * width, -width / 2, width / 2, 1.5 * width)):
    lines[0, i, :, 0] = road + center + off
  lane_stds[0, 1, :, 0], lane_stds[0, 2, :, 0] = stds
  lane_probs = np.zeros((1, 8))
  lane_probs[0, 3], lane_probs[0, 5] = probs
  path = np.zeros((1, 33, 3))
  path[0, :, 0] = X
  path[0, :, 1] = road + plan * np.clip(X / 10, 0, 1)
  return {'lane_lines': lines, 'lane_lines_stds': lane_stds, 'lane_lines_prob': lane_probs, 'plan': path}


def drive(bf, seconds, v=20.0, k=0.0, **kw):
  out = [bf.update(frame(k=k, **kw), v, True, k) for _ in range(int(seconds / DT_MDL))]
  return np.array(out) * v ** 2  # m/s^2


class TestBlendful(OpenpilotTestCase):
  def setup_method(self):
    self.bf = Blendful()

  def test_centered_adds_nothing(self):
    push = drive(self.bf, 5.0)
    assert self.bf.trust > 0.9
    assert np.abs(push).max() < 1e-3

  def test_pulls_toward_lane_center(self):
    push = drive(self.bf, 5.0, center=0.5)
    assert push[-1] > 0.02  # + y side, where the lane center is
    assert self.bf.trust > 0.9
    assert np.all(np.diff(push) <= BUILD * DT_MDL + 1e-9)

  def test_flipping_sides_builds_slowly(self):
    k = 0.002  # 0.8 m/s^2 at 20 m/s
    drive(self.bf, 5.0, k=k, center=0.5)
    push = drive(self.bf, 5.0, k=k, center=-0.5)
    rate = np.diff(push) / DT_MDL
    assert push[-1] < 0
    assert np.all(rate >= -RELEASE - 1e-6)
    assert np.all(rate[push[:-1] <= 0] >= -BUILD - 1e-6)  # once past zero it builds
    crossing = push[1:][(push[:-1] > 0) & (push[1:] <= 0)]
    assert len(crossing) and np.all(crossing >= -BUILD * DT_MDL - 1e-9)

  def test_weak_lines_drive_laneless(self):
    clear = drive(Blendful(), 5.0, center=0.5)[-1]
    faint = Blendful()
    push = drive(faint, 5.0, center=0.5, probs=(0.1, 0.1))
    assert faint.trust < 0.25 and abs(push[-1]) < 0.25 * clear  # faint lines = trust and push scale down
    blurry = Blendful()
    push = drive(blurry, 5.0, center=0.5, stds=(0.8, 0.8))
    assert blurry.trust == 0.0 and np.abs(push).max() < 1e-6  # lines too uncertain = laneless

  def test_lone_line_holds_through_a_blink_in_a_curve(self):
    k, v = 1 / 20, 6.0
    drive(self.bf, 6.0, v=v, k=k, plan=0.4, probs=(0.9, 0.05))
    before = self.bf.trust
    drive(self.bf, 0.25, v=v, k=k, plan=0.4, probs=(0.1, 0.05), stds=(1.0, 0.1))
    bottom = self.bf.trust
    drive(self.bf, 2.0, v=v, k=k, plan=0.4, probs=(0.9, 0.05))
    assert before > 0.5
    assert bottom > 0.5 * before  # keeps latched through flicker
    assert self.bf.trust > 0.85 * before

  def test_yields_when_the_model_goes_around(self):
    drive(self.bf, 6.0)
    push = drive(self.bf, 3.0, plan=0.8)
    assert self.bf.going_around
    assert self.bf.trust < 0.05
    assert abs(push[-1]) < 0.01

  def test_fit_does_not_grow_while_trust_falls(self):
    drive(self.bf, 5.0, center=0.3)
    for i in range(40):
      dk, trust = self.bf.dk, self.bf.trust
      p = 0.9 - 0.02 * i
      self.bf.update(frame(center=0.3, plan=-0.02 * i, probs=(p, p)), 20.0, True, 0.0)
      if self.bf.trust < trust:
        assert abs(self.bf.dk) <= abs(dk) + 1e-12

  def test_toggle_off_returns_zero_and_resets(self):
    drive(self.bf, 5.0, center=0.5)
    assert self.bf.curvature != 0.0
    assert self.bf.update(frame(center=0.5), 20.0, True, 0.0, enabled=False) == 0.0
    assert self.bf.curvature == 0.0 and self.bf.trust == 0.0

  def test_fades_below_min_speed(self):
    drive(self.bf, 5.0, v=10.0, center=0.5)
    start = self.bf.curvature
    out = np.array([self.bf.update(frame(center=0.5), 4.0, True, 0.0) for _ in range(100)])
    assert self.bf.trust == 0.0
    assert abs(out[0]) < abs(start)
    assert abs(out[-1]) < 1e-6


class TestDefenderBlendful(OpenpilotTestCase):
  def setup_method(self):
    self.bf = Blendful(guard_lane_center=True)

  def test_centers_in_both_directions_without_crossing(self):
    for center in (-0.12, 0.12):
      self.bf = Blendful(guard_lane_center=True)
      out = drive(self.bf, 5.0, center=center)
      correction = out[-1] / (20.0 ** 2)
      assert correction * center > 0
      assert abs(correction) * 25.0 ** 2 / 2 <= abs(center)
      assert np.all(np.abs(np.diff(out)) <= BUILD * DT_MDL + 1e-9)

  def test_rejects_original_fit_that_points_away_from_center(self):
    # The base curvature is straight, but the published plan is left of center.
    sample = frame(center=-0.2, plan=-0.35)
    legacy = Blendful()
    for _ in range(100):
      assert self.bf.update(sample, 20.0, True, 0.0) == 0.0
      legacy.update(sample, 20.0, True, 0.0)
    assert legacy.curvature < 0

  def test_clears_stored_correction_when_offset_reverses(self):
    previous = drive(self.bf, 5.0, center=0.5)[-1]
    next_correction = self.bf.update(frame(center=-0.5), 20.0, True, 0.0) * 20.0 ** 2
    assert previous > 0 and next_correction == 0.0
    assert previous - next_correction <= RELEASE * DT_MDL + 1e-9

  def test_requires_two_reliable_lines_and_agreement_at_each_distance(self):
    opposing = frame(center=0.2)
    opposing['plan'][0, :, 1] = np.interp(X, [0, 15, 20, 25], [0, 0, 0.2, 0.4])
    invalid = frame(center=0.2)
    invalid['lane_lines'][0, 1, 12, 0] = np.nan
    too_short = frame(center=0.2)
    too_short['plan'][0, :, 0] = np.minimum(X, 24)
    for sample in (opposing, invalid, too_short, frame(center=0.2, probs=(0.99, 0.5)), frame(center=0.2, stds=(0.1, 0.4))):
      with self.subTest(sample=sample):
        assert drive(self.bf, 5.0, center=0.2)[-1] > 0.0
        for _ in range(30):
          assert self.bf.update(sample, 20.0, True, 0.0) == 0.0

  def test_override_and_toggle_clear_correction_and_require_new_confirmation(self):
    sample = frame(center=0.2)
    assert drive(self.bf, 5.0, center=0.2)[-1] > 0.0
    assert self.bf.update(sample, 20.0, False, 0.0) == 0.0
    assert self.bf.update(sample, 20.0, True, 0.0) == 0.0
    assert self.bf.update(sample, 20.0, True, 0.0, enabled=False) == 0.0
    assert self.bf.guard_lane_center
    assert self.bf.update(sample, 20.0, True, 0.0) == 0.0

  def test_yields_to_model_avoidance(self):
    drive(self.bf, 6.0)
    push = drive(self.bf, 3.0, plan=0.8)
    assert self.bf.going_around
    assert np.all(push == 0.0)

  def test_preference_levels_are_symmetric_and_bounded_in_curves(self):
    for level in (1, 2, 3):
      left, right = Blendful(True, -level), Blendful(True, level)
      a = drive(left, 5.0, k=-0.001, plan=0.17)
      b = drive(right, 5.0, k=0.001, plan=-0.17)
      np.testing.assert_allclose(a, -b, atol=1e-12)
      assert a[-1] < 0 < b[-1]
      assert np.isclose(right.preferred_offset, level * 0.10 / 3)
      assert np.isclose(left.preferred_offset, -right.preferred_offset)
      assert np.max(np.abs(b)) <= 0.10000001

  def test_narrowest_checked_width_limits_preference_and_reacquires_slowly(self):
    sample = frame(width=3.6)
    bf = Blendful(True, 3)
    drive(bf, 2.0)
    assert bf.preferred_offset == 0.10
    # The road tapers toward 25 m. Its narrowest width limits the entire target.
    sample['lane_lines'][0, 2, X >= 21, 0] -= 0.98
    bf.update(sample, 20.0, True, 0.0)
    assert np.isclose(bf.preferred_offset, 0.02)
    assert bf.update(frame(probs=(0.5, 0.99)), 20.0, True, 0.0) == 0.0
    assert bf.reason == "laneGeometry" and bf.preferred_offset == 0.0
    assert bf.update(frame(), 20.0, True, 0.0) == 0.0
    assert 0 < bf.preferred_offset <= 0.05 * DT_MDL
    assert bf.update(frame(), 20.0, False, 0.0) == 0.0
    assert bf.reason == "inactive" and bf.preferred_offset == 0.0

  def test_preference_ignores_invalid_level_and_preserves_disabled_and_yield(self):
    for bf in (Blendful(True, 4), Blendful(False, -3)):
      drive(bf, 2.0)
      assert bf.preference == 0 and bf.preferred_offset == 0.0
    for level in (-3, 3):
      bf = Blendful(True, level)
      drive(bf, 6.0)
      assert np.all(drive(bf, 3.0, plan=0.8) == 0.0)
      assert bf.going_around and bf.reason == "yielding"
      assert bf.update(frame(), 20.0, True, 0.0, enabled=False) == 0.0
      assert bf.reason == "disabled" and bf.preference == level and bf.preferred_offset == 0.0
