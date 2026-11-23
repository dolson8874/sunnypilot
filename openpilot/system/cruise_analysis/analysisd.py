"""Isolated bounded observer, independent of the display option and vehicle control."""
import faulthandler
import json
import math
import signal
import time

from openpilot.cereal import messaging
from openpilot.cereal.services import SERVICE_LIST
from openpilot.common.swaglog import cloudlog
from openpilot.system.cruise_analysis.observer import MAX_EVENT_BYTES, Observer

INPUTS = ('can', 'carState', 'carControl', 'carOutput', 'carParams', 'carParamsSP',
          'accelerometer', 'gyroscope')


def json_value(value):
  if isinstance(value, bytes):
    return {'bytesHex': value.hex()}
  if isinstance(value, float) and not math.isfinite(value):
    return {'nonFinite': str(value)}
  if isinstance(value, dict):
    return {k: json_value(v) for k, v in value.items()}
  if isinstance(value, (list, tuple)):
    return [json_value(v) for v in value]
  return value


# msgq requires three aligned messages (including its 8-byte length) per queue.
# Keep a separate application budget even when transport capacity is enlarged.
MAX_SNAPSHOT_BYTES = 200000


def message_fits(size):
  aligned = (size + 8 + 7) // 8 * 8
  return size <= MAX_SNAPSHOT_BYTES and 3 * aligned <= SERVICE_LIST['cruiseAnalysis'].queue_size


def make_message(observer, now_ns):
  message = None
  snapshot = json_value(observer.snapshot(now_ns))

  def encode():
    nonlocal message
    # Allocate a fresh arena: replacing Text leaves the old allocation serialized.
    message = messaging.new_message('cruiseAnalysis')
    message.valid = True
    message.cruiseAnalysis.version = 1
    message.cruiseAnalysis.snapshotJson = json.dumps(snapshot, separators=(',', ':'), allow_nan=False, ensure_ascii=False)
    size = len(message.to_bytes())
    message.clear_write_flag()
    return size

  if not message_fits(encode()):
    observer.counts['budgetExceeded'] += 1
    snapshot['counts'] = dict(observer.counts)
    snapshot['context'] = {}
    snapshot['frames'] = {}
    snapshot['snapshotOmitted'] = 'sizeBudget;seeOriginalRlogEvents'
    if not message_fits(encode()):
      # Any field, including radar diagnostics or an error string, may grow.
      snapshot = {'version': 1, 'epoch': str(observer.epoch)[:64], 'snapshotMonoTime': now_ns,
                  'counts': dict(observer.counts), 'snapshotOmitted': 'sizeBudget;seeOriginalRlogEvents'}
      if not message_fits(encode()):
        raise ValueError('cruiseAnalysis transport budget cannot hold a minimal snapshot')
  return message


def consume_raw(observer, name, raw, receive_ns):
  if len(raw) > MAX_EVENT_BYTES:
    observer.counts['budgetExceeded'] += 1
    return
  try:
    event = messaging.log_from_bytes(raw)
    if event.which() != ('can' if name == 'flexray' else name):
      observer.counts['rejected'] += 1
      return
    observer.consume(event, receive_ns, name)
  except Exception as exc:
    observer.counts['errors'] += 1
    observer.last_error = f'{type(exc).__name__}: {exc}'[:256]


def main():
  faulthandler.enable()
  cloudlog.info('cruise_analysis starting queue_bytes=%d snapshot_budget=%d',
                SERVICE_LIST['cruiseAnalysis'].queue_size, MAX_SNAPSHOT_BYTES)
  stopping = False

  def stop(_signum, _frame):
    nonlocal stopping
    stopping = True

  signal.signal(signal.SIGTERM, stop)
  signal.signal(signal.SIGINT, stop)
  observer = Observer()
  sockets = {name: messaging.sub_sock(name, conflate=name != 'can') for name in INPUTS}
  pm = messaging.PubMaster(['cruiseAnalysis'])
  publish_at = 0.0
  while not stopping:
    # Bounded work per input and per pass, so a busy CAN stream cannot starve status publication.
    for name, sock in sockets.items():
      for _ in range(64):
        raw = sock.receive(non_blocking=True)
        if raw is None:
          break
        consume_raw(observer, name, raw, time.monotonic_ns())
    now = time.monotonic()
    if now >= publish_at:
      try:
        message = make_message(observer, time.monotonic_ns()).to_bytes()
        if not message_fits(len(message)):
          raise ValueError('cruiseAnalysis serialized message exceeds transport budget')
        pm.send('cruiseAnalysis', message)
      except Exception as exc:
        observer.counts['errors'] += 1
        observer.last_error = f'publish {type(exc).__name__}: {exc}'[:256]
        cloudlog.error('cruise_analysis %s', observer.last_error)
      publish_at = now + 0.5
    time.sleep(0.01)


if __name__ == '__main__':
  main()
