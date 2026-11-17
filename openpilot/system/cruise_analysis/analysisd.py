"""Isolated bounded observer, independent of the display option and vehicle control."""
import json
import math
import signal
import time

from openpilot.cereal import messaging
from openpilot.system.cruise_analysis.observer import MAX_EVENT_BYTES, Observer

INPUTS = ('can', 'flexray', 'carState', 'carControl', 'carOutput', 'carParams', 'carParamsSP',
          'accelerometer', 'gyroscope', 'flexrayStatus')


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


def make_message(observer, now_ns):
  message = messaging.new_message('cruiseAnalysis')
  message.valid = True
  message.cruiseAnalysis.version = 1
  snapshot = json_value(observer.snapshot(now_ns))
  encoded = json.dumps(snapshot, separators=(',', ':'), allow_nan=False)
  if len(encoded) > 200000:
    snapshot['context'] = {}
    snapshot['frames'] = {}
    snapshot['snapshotOmitted'] = 'sizeBudget;seeOriginalRlogEvents'
    encoded = json.dumps(snapshot, separators=(',', ':'), allow_nan=False)
  message.cruiseAnalysis.snapshotJson = encoded
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
  stopping = False

  def stop(_signum, _frame):
    nonlocal stopping
    stopping = True

  signal.signal(signal.SIGTERM, stop)
  signal.signal(signal.SIGINT, stop)
  observer = Observer()
  sockets = {name: messaging.sub_sock(name, conflate=name not in ('can', 'flexray')) for name in INPUTS}
  pm = messaging.PubMaster(['cruiseAnalysis'])
  publish_at = 0.0
  while not stopping:
    # Bounded work per input and per pass, so a busy CAN/FR stream cannot starve status publication.
    for name, sock in sockets.items():
      for _ in range(64):
        raw = sock.receive(non_blocking=True)
        if raw is None:
          break
        consume_raw(observer, name, raw, time.monotonic_ns())
    now = time.monotonic()
    if now >= publish_at:
      try:
        pm.send('cruiseAnalysis', make_message(observer, time.monotonic_ns()))
      except Exception as exc:
        observer.counts['errors'] += 1
        observer.last_error = f'publish {type(exc).__name__}: {exc}'[:256]
      publish_at = now + 0.5
    time.sleep(0.01)


if __name__ == '__main__':
  main()
