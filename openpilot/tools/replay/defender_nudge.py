"""Compare a Defender CAN0 0x2E sign hypothesis to recorded manual Nudge inputs."""
import argparse
import csv
import sys

from openpilot.tools.lib.logreader import LogReader


def samples(events):
  torque = state = None
  for event in events:
    now = event.logMonoTime
    kind = event.which()
    if kind == "can":
      if not event.valid:
        torque = None
        continue
      for frame in event.can:
        if frame.src == 0 and frame.address == 0x2E:
          torque = (now, frame.dat[1] >> 6 & 1, frame.dat[3]) if len(frame.dat) == 4 else None
    elif kind == "carState":
      state = (now, event.carState) if event.valid and event.carState.canValid else None
    elif kind == "modelV2" and event.valid and state and torque:
      if not all(0 <= now - ts <= 100_000_000 for ts in (torque[0], state[0])):
        continue
      car = state[1]
      if car.leftBlinker == car.rightBlinker:
        continue
      right = car.rightBlinker
      bit, magnitude = torque[1:]
      candidate = -magnitude if bit else magnitude
      yield (now, "right" if right else "left", str(event.modelV2.meta.laneChangeState),
             int(car.steeringPressed), bit, magnitude, car.steeringTorque, candidate,
             int(car.steeringPressed and (candidate < 0 if right else candidate > 0)))


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("rlog", nargs="+", help="local Defender rlog segment files")
  args = parser.parse_args()
  writer = csv.writer(sys.stdout)
  writer.writerow(("logMonoTime", "blinker", "recordedLaneChangeState", "steeringPressed", "bit6",
                   "rawMagnitude", "recordedTorque", "candidateTorque", "candidateDirectionMatches"))
  for path in args.rlog:
    writer.writerows(samples(LogReader(path)))
