import time

import numpy as np
from cereal import log
import cereal.messaging as messaging

from openpilot.common.realtime import DT_MDL
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, MIN_SPEED
from openpilot.selfdrive.controls.lib.lane_planner_2 import LanePlanner
from openpilot.selfdrive.controls.lib.lateral_mpc_lib.lat_mpc import LateralMpc
from openpilot.selfdrive.controls.lib.lateral_mpc_lib.lat_mpc import N as LAT_MPC_N


TRAJECTORY_SIZE = 33

PATH_COST = 1.0
LATERAL_MOTION_COST = 0.11
LATERAL_ACCEL_COST = 0.0
LATERAL_JERK_COST = 0.04
STEERING_RATE_COST = 700.0


class LateralPlanner:
  def __init__(self, CP, debug=False):
    self.factor1 = CP.wheelbase - CP.centerToFront
    self.factor2 = (CP.centerToFront * CP.mass) / (CP.wheelbase * CP.tireStiffnessRear)

    self.last_cloudlog_t = 0.0
    self.solution_invalid_cnt = 0

    self.path_xyz = np.zeros((TRAJECTORY_SIZE, 3))
    self.velocity_xyz = np.zeros((TRAJECTORY_SIZE, 3))
    self.v_plan = np.zeros((TRAJECTORY_SIZE,))
    self.x_sol = np.zeros((TRAJECTORY_SIZE, 4), dtype=np.float32)
    self.v_ego = MIN_SPEED

    self.debug_mode = debug
    self.params = Params()
    self.LP = LanePlanner()
    self.read_params_countdown = 0
    self.lanelines_active = False

    self.use_lane_line_speed_apply = self.params.get("UseLaneLineSpeed", return_default=True)
    self.use_lane_line_mode = False

    self.plan_yaw = np.zeros((TRAJECTORY_SIZE,))
    self.plan_yaw_rate = np.zeros((TRAJECTORY_SIZE,))
    self.plan_a = np.zeros((TRAJECTORY_SIZE,))
    self.t_idxs = np.arange(TRAJECTORY_SIZE)
    self.y_pts = np.zeros((TRAJECTORY_SIZE,))

    self.lat_mpc = LateralMpc()
    self.reset_mpc(np.zeros(4))

    self.lanemode_possible_count = 0
    self.laneless_only = True

  def reset_mpc(self, x0=None):
    if x0 is None:
      x0 = np.zeros(4)
    self.x0 = x0
    self.lat_mpc.reset(x0=self.x0)

  def update(self, sm):
    self.read_params_countdown -= 1
    if self.read_params_countdown <= 0:
      self.read_params_countdown = 100
      self.use_lane_line_speed_apply = self.params.get("UseLaneLineSpeed", return_default=True)

    measured_curvature = sm['controlsState'].curvature
    v_ego_car = max(sm['carState'].vEgo, MIN_SPEED)
    speed_kph = v_ego_car * 3.6
    self.v_ego = v_ego_car

    md = sm['modelV2']
    model_active = False
    if len(md.position.x) == TRAJECTORY_SIZE and len(md.orientation.x) == TRAJECTORY_SIZE:
      model_active = True
      self.path_xyz = np.column_stack([md.position.x, md.position.y, md.position.z])
      self.t_idxs = np.array(md.position.t)
      self.plan_yaw = np.array(md.orientation.z)
      self.plan_yaw_rate = np.array(md.orientationRate.z)
      self.velocity_xyz = np.column_stack([md.velocity.x, md.velocity.y, md.velocity.z])
      car_speed = np.linalg.norm(self.velocity_xyz, axis=1)
      self.v_plan = np.clip(car_speed, MIN_SPEED, np.inf)
      self.v_ego = self.v_plan[0]
      self.plan_a = np.array(md.acceleration.x)

      if md.velocity.x[-1] < md.velocity.x[0] * 0.7:
        self.lanemode_possible_count = 0
        self.laneless_only = True
      else:
        self.lanemode_possible_count += 1
        if self.lanemode_possible_count > int(1 / DT_MDL):
          self.laneless_only = False

    self.LP.parse_model(md)

    if self.use_lane_line_speed_apply == 0 or self.laneless_only:
      self.use_lane_line_mode = False
    elif speed_kph >= self.use_lane_line_speed_apply + 2:
      self.use_lane_line_mode = True
    elif speed_kph < self.use_lane_line_speed_apply - 2:
      self.use_lane_line_mode = False

    if md.meta.laneChangeState != log.LateralPlan.LaneChangeState.off:
      self.LP.lane_change_multiplier = 0.0
    else:
      self.LP.lane_change_multiplier = 1.0

    self.LP.lanefull_mode = self.use_lane_line_mode
    self.path_xyz, self.lanelines_active = self.LP.get_d_path(v_ego_car, self.t_idxs, self.path_xyz, curve_speed=0.0)

    if self.lanelines_active:
      self.plan_yaw, self.plan_yaw_rate = yaw_from_path_no_scipy(
        self.path_xyz,
        self.v_plan,
        smooth_window=5,
        clip_rate=2.0,
        align_first_yaw=None,
      )

    self.lat_mpc.set_weights(
      PATH_COST,
      LATERAL_MOTION_COST,
      LATERAL_ACCEL_COST,
      LATERAL_JERK_COST,
      STEERING_RATE_COST,
    )

    y_pts = self.path_xyz[: LAT_MPC_N + 1, 1]
    heading_pts = self.plan_yaw[: LAT_MPC_N + 1]
    yaw_rate_pts = self.plan_yaw_rate[: LAT_MPC_N + 1]
    self.y_pts = y_pts

    lateral_factor = np.clip(self.factor1 - (self.factor2 * self.v_plan**2), 0.0, np.inf)
    p = np.column_stack([self.v_plan, lateral_factor])
    self.lat_mpc.run(self.x0, p, y_pts, heading_pts, yaw_rate_pts)

    self.x0[3] = np.interp(DT_MDL, self.t_idxs[: LAT_MPC_N + 1], self.lat_mpc.x_sol[:, 3])

    mpc_nans = np.isnan(self.lat_mpc.x_sol[:, 3]).any()
    t = time.monotonic()
    if mpc_nans or self.lat_mpc.solution_status != 0:
      self.reset_mpc()
      self.x0[3] = measured_curvature * self.v_ego
      if t > self.last_cloudlog_t + 5.0:
        self.last_cloudlog_t = t
        cloudlog.warning("Lateral mpc invalid solution")

    if self.lat_mpc.cost > 1e6 or mpc_nans:
      self.solution_invalid_cnt += 1
    else:
      self.solution_invalid_cnt = 0

    self.x_sol = self.lat_mpc.x_sol

  def publish(self, sm, pm):
    plan_solution_valid = self.solution_invalid_cnt < 2

    plan_send = messaging.new_message('lateralPlan')
    plan_send.valid = sm.all_checks(service_list=['carState', 'controlsState', 'modelV2'])

    lateral_plan = plan_send.lateralPlan
    lateral_plan.modelMonoTime = sm.logMonoTime['modelV2']
    lateral_plan.dPathPoints = self.y_pts.tolist()
    lateral_plan.psis = self.lat_mpc.x_sol[0:CONTROL_N, 2].tolist()

    v_div = np.maximum(self.v_plan[:CONTROL_N], 6.0)
    if len(self.v_plan) == TRAJECTORY_SIZE:
      lateral_plan.curvatures = (self.lat_mpc.x_sol[0:CONTROL_N, 3] / v_div).tolist()
    else:
      lateral_plan.curvatures = (self.lat_mpc.x_sol[0:CONTROL_N, 3] / self.v_ego).tolist()

    v_div2 = max(self.v_ego, 6.0)
    lateral_plan.curvatureRates = [float(x.item() / v_div2) for x in self.lat_mpc.u_sol[0 : CONTROL_N - 1]] + [0.0]

    lateral_plan.mpcSolutionValid = bool(plan_solution_valid)
    lateral_plan.solverExecutionTime = self.lat_mpc.solve_time

    if self.debug_mode:
      lateral_plan.solverCost = self.lat_mpc.cost
      lateral_plan.solverState = log.LateralPlan.SolverState.new_message()
      lateral_plan.solverState.x = self.lat_mpc.x_sol.tolist()
      lateral_plan.solverState.u = self.lat_mpc.u_sol.flatten().tolist()

    lateral_plan.useLaneLines = self.lanelines_active
    lateral_plan.desire = log.LateralPlan.Desire.none
    lateral_plan.laneChangeState = sm['modelV2'].meta.laneChangeState
    lateral_plan.laneChangeDirection = sm['modelV2'].meta.laneChangeDirection

    pm.send('lateralPlan', plan_send)


def smooth_moving_avg(arr, window=5):
  if window < 2:
    return arr
  if window % 2 == 0:
    window += 1
  pad = window // 2
  arr_pad = np.pad(arr, (pad, pad), mode='edge')
  kernel = np.ones(window) / window
  return np.convolve(arr_pad, kernel, mode='same')[pad:-pad]


def yaw_from_path_no_scipy(path_xyz, v_plan, smooth_window=5, clip_rate=2.0, align_first_yaw=None):
  del align_first_yaw
  v0 = float(np.asarray(v_plan)[0]) if len(v_plan) else 0.0
  if v0 <= 6.0:
    smooth_window = max(smooth_window, 9)

  n = path_xyz.shape[0]
  x = path_xyz[:, 0].astype(float)
  y = path_xyz[:, 1].astype(float)

  if n < 5:
    return np.zeros(n, np.float32), np.zeros(n, np.float32)

  dx = np.diff(x)
  dy = np.diff(y)
  ds_seg = np.sqrt(dx * dx + dy * dy)
  ds_seg[ds_seg < 0.05] = 0.05
  s = np.zeros(n, float)
  s[1:] = np.cumsum(ds_seg)
  if s[-1] < 0.5:
    return np.zeros(n, np.float32), np.zeros(n, np.float32)

  x_smooth = smooth_moving_avg(x, smooth_window)
  y_smooth = smooth_moving_avg(y, smooth_window)

  dx_ds = np.gradient(x_smooth, s)
  dy_ds = np.gradient(y_smooth, s)
  d2x_ds2 = np.gradient(dx_ds, s)
  d2y_ds2 = np.gradient(dy_ds, s)

  yaw = np.arctan2(dy_ds, dx_ds)
  yaw = np.unwrap(yaw)

  denom = np.maximum(dx_ds * dx_ds + dy_ds * dy_ds, 1e-6) ** 1.5
  curvature = (dx_ds * d2y_ds2 - dy_ds * d2x_ds2) / denom
  v = np.asarray(v_plan, dtype=float)
  v = np.pad(v, (0, max(0, n - len(v))), mode='edge')[:n]
  yaw_rate = curvature * np.maximum(v, 0.1)

  if clip_rate > 0.0:
    yaw_rate = np.clip(yaw_rate, -clip_rate, clip_rate)

  return yaw.astype(np.float32), yaw_rate.astype(np.float32)
