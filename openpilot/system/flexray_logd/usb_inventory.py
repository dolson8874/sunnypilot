"""Read-only USB descriptor capture, isolated from SPI acquisition."""
import json
import os
import select
import subprocess
import threading
import time

from openpilot.common.swaglog import cloudlog


def capture_usb_inventory(command=('lsusb', '-v', '-d', '0403:6011'), timeout=5.0, limit=32768):
  result = {'command': list(command), 'returncode': None, 'timed_out': False, 'output': '', 'truncated': False, 'bytes': 0}
  output = bytearray()
  process = None
  try:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + timeout
    os.set_blocking(process.stdout.fileno(), False)
    while True:
      left = deadline - time.monotonic()
      if left <= 0:
        result['timed_out'] = True
        break
      if not select.select([process.stdout], [], [], min(left, 0.1))[0]:
        continue
      try:
        block = os.read(process.stdout.fileno(), 8192)
      except BlockingIOError:
        continue
      if not block:
        break
      result['bytes'] += len(block)
      output.extend(block[:max(0, limit - len(output))])
  except OSError as error:
    result['error'] = str(error)
  finally:
    if process is not None:
      try:
        process.wait(timeout=max(0.0, deadline - time.monotonic()))
      except subprocess.TimeoutExpired:
        result['timed_out'] = True
        process.kill()
        process.wait()
      process.stdout.close()
      result['returncode'] = process.returncode
  result['output'] = output.decode('utf-8', errors='replace')
  result['truncated'] = result['bytes'] > limit
  return result


class UsbInventory:
  def __init__(self):
    self.result = None
    self.reported = False
    self.thread = threading.Thread(target=self._collect, name='flexray-lsusb', daemon=True)
    self.thread.start()

  def _collect(self):
    self.result = capture_usb_inventory()

  def report(self):
    # Keep cloudlog's IPC socket and daemon context on the publisher thread.
    if self.result is not None and not self.reported:
      cloudlog.info('FlexRay USB descriptor: ' + json.dumps(self.result))
      self.reported = True


def start_usb_inventory():
  return UsbInventory()
