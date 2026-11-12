"""C3 process integration without depending on the model-runner configuration."""
from openpilot.system.manager.process import PythonProcess


def flexray_logging(started, params, CP):
  # Match this branch's loggerd onroad/notCar/DisableLogging condition.
  return started and ((not CP.notCar) or not params.get_bool('DisableLogging')) and params.get_bool('FlexrayLoggingEnabled')


class FlexrayProcess(PythonProcess):
  def start(self):
    if self.proc is not None and self.proc.exitcode is not None:
      self.stop()
    super().start()
