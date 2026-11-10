# Cabana

Cabana is a tool developed to view raw CAN data. One use for this is creating and editing [CAN Dictionaries](http://socialledge.com/sjsu/index.php/DBC_Format) (DBC files), and the tool provides direct integration with [commaai/opendbc](https://github.com/commaai/opendbc) (a collection of DBC files), allowing you to load the DBC files direct from source, and save to your fork. In addition, you can load routes from [comma connect](https://connect.comma.ai).

## Usage Instructions

```bash
$ ./cabana -h
Usage: ./cabana [options] [route]

  route                     the drive to replay. find your drives at connect.comma.ai

Options:
  --help                    show this help
  --demo                    use a demo route instead of providing your own
  --auto                    Auto load the route from the best available source (no video):
                            internal, openpilotci, comma_api, car_segments, testing_closet
  --qcam                    load qcamera
  --wide-road               load wide road camera (alias: --ecam)
  --cabin                   load cabin camera (alias: --dcam)
  --msgq                    read can messages from the msgq
  --panda                   read can messages from panda
  --panda-serial <serial>   read can messages from panda with given serial
  --socketcan <device>      read can messages from given SocketCAN device
  --zmq <ip-address>        read can messages from zmq at the specified ip-address
  --data_dir <dir>          local directory with routes
  --no-vipc                 do not output video
  --no-cache                turn off the local route file cache
  --dbc <file>              dbc file to open
```

## Examples

### Running Cabana in Demo Mode
To run Cabana using a built-in demo route, use the following command:

```shell
cabana --demo
```

### Loading a Specific Route

To load a specific route for replay, provide the route as an argument:

```shell
cabana "5beb9b58bd12b691/0000010a--a51155e496"
```

Replace "5beb9b58bd12b691/0000010a--a51155e496" with your desired route identifier.


### Running Cabana with multiple cameras
To run Cabana with multiple cameras, use the following command:

```shell
cabana "5beb9b58bd12b691/0000010a--a51155e496" --cabin --wide-road
```

### Streaming CAN Messages from a comma Device

[SSH into your device](https://github.com/commaai/openpilot/wiki/SSH) and start the bridge with the following command:

```shell
cd /data/openpilot
./openpilot/cereal/messaging/bridge &
```

Then Run Cabana with the device's IP address:

```shell
cabana --zmq <ipaddress>
```

Replace &lt;ipaddress&gt; with your comma device's IP address.

While streaming from the device, Cabana will log the CAN messages to a local directory. By default, this directory is ~/cabana_live_stream/. You can change the log directory in Cabana by navigating to menu -> tools -> settings.

After disconnecting from the device, you can replay the logged CAN messages from the stream selector dialog -> browse local route.

### Streaming CAN Messages from Panda

To read CAN messages from a connected Panda, use the following command:

```shell
cabana --panda
```

### Using the Stream Selector Dialog

If you run Cabana without any arguments, a stream selector dialog will pop up, allowing you to choose the stream.

```shell
cabana
```

## Additional Information

### FlexRay cycle classification

Keep the original frame ID in the capture and classify signals with Cabana's existing DBC Multiplexor.

`openpilot/system/flexray_logd` retains its old ID/counter classification code but does not execute it.
The dedicated `flexray` channel carries standard `Event.can` messages into the driving route's rlog.
Route replay uses the existing CAN event reader; device streaming subscribes to both `can` and `flexray`.
Full FlexRay frames are not included in qlog. Stored frames use sources 4–11 (4 + received bus),
so the current board's bus 2 appears as source 6 without colliding with car CAN bus 2.
The stored and displayed bytes retain `flags (1 byte) + counter (1 byte) + payload + CRC (3 bytes)`.
Raw dump files remain separate from routes and cannot be opened directly as a Cabana route.

Open [the example DBC](dbc/examples/flexray_cycle.dbc) for frame ID `0x000F` on its FlexRay source
(use **Manage DBCs → FlexRay bus 2 / source 6** for the current board).
It illustrates a four-byte payload; adjust the message length and payload signals to your data.
In Cabana's signal editor:

1. Set a little-endian signal at start bit **8** as **Multiplexor Signal**.
2. Use size **1**, **2**, **3**, **4**, or **6** bits for counter modulo **2**, **4**, **8**, **16**, or **64**.
3. Set each conditional payload signal to **Multiplexed Signal** and select its **Multiplex Value**.
   Payload starts at bit **16**; normal signals apply to every cycle.

The example uses `m0` for even cycles and `m1` for odd cycles at the same payload position.
Select either signal to plot only its matching cycles; the message list retains one row per bus/frame ID.
This does not reproduce vehicle-specific exceptions from the old classification table automatically.
Existing captures with already transformed IDs are not converted back by loading this DBC.

For more information, see the [openpilot wiki](https://github.com/commaai/openpilot/wiki/Cabana)

### Bidirectional FPGA SPI logs

The receiver preserves bulk-read fragments; USB/SPI chunks are not frame boundaries.
It accepts exactly the following marker/direction pairs:

| Wire prefix | Direction | Wire bus | rlog/Cabana source |
| --- | --- | --- | --- |
| `CA A0` | DADC → BCM-side | 2 | 6 |
| `CA 80` | BCM-side → DADC | 0 | 4 |

DADC logs are the FPGA's **modified forwarding output**, not its unmodified input.
“BCM-side” names the source segment, not a guarantee of transmission by the BCM ECU.
The original Frame ID and flags/cycle/payload/CRC body are preserved on both sources.
Existing cycle multiplexing still starts at bit 8 of the body. Load the appropriate
FlexRay DBC for each source independently.

A wire frame contains `CA`, marker, five FlexRay header bytes, duplicated flags and
cycle, `words*2` payload bytes, and three MSB-first frame-CRC bytes. Total wire length
is `payload + 12`, with `words=0..127`. Header CRC, length, duplicated metadata and frame
CRC are checked before acceptance. Payload bytes resembling markers remain payload.
A failed candidate is retried at its start plus one byte. Partial markers/frames survive
across reads. The direction marker is outside the existing FlexRay CRC coverage;
marker corruption can therefore mislabel a direction without failing CRC. No new
wire timestamps, sequence fields or protocol bytes are added.

The transport remains FT4232H Interface B, SPI mode 0 at **7.5 MHz**. The FT2232H
Fast Serial and existing A0-only raw replay paths remain available.

The MPSSE reader keeps at most two command chunks outstanding (32768 bytes each,
65536 response bytes total with the normal collector). It replenishes while receiving
responses; other GPIO/clock/read commands are blocked until the stream is closed.
H-class divide-by-5 selection matches the divisor calculation and rounds down the
configured frequency. `configured_clock` is calculated from the selected clock/divisor,
not a board timing measurement. The default remains 7.5 MHz; arithmetic tests at
10 MHz do not establish 10 MHz board operation.

Every USB packet's two FTDI status bytes are removed. Available payload is retained
across soft timeout/interrupted transfers and buffered remainder reads. Empty reads
resume without a collector restart; one second without progress is fatal. Short
command writes/fatal errors are sticky, with valid received prefixes delivered before
the error and no further read commands submitted. Stop requests cease replenishment
and drain pending responses for at most one second; USB timeouts are clipped to the
remaining deadline. No new USB read starts after that deadline. Buffered host bytes
can still be returned without USB waiting. Undrained responses/close failures mark the
capture incomplete; pending responses can include padding, so their count is not an
exact number of lost FlexRay bytes or frames.

`SPI:` reports separate status-free actual USB payload bytes/rate, delivered bytes,
USB read calls, MPSSE command count, pending/buffered/peak bytes, soft timeouts and
interruptions, cumulative USB/call time and maximum gap between calls. USB payload
read-ahead can temporarily exceed bytes delivered to the parser by the buffered
remainder. These are host observations, not a substitute for physical SPI I/O timing.
The capture `bulk_*` counters count reader-return bytes/batches, including buffered
remainder; actual USB operations and payload are the separate SPI counters.


Capture's `flexray_stats` stderr reports once per second and at input shutdown include
bulk reads/bytes, validated frames/wire bytes per direction, zero padding outside
frames, nonpadding noise, header/frame CRC errors, metadata errors and recoveries.
Ordinary searches after valid frames and zero padding do not count as recoveries.
Socket queue drops/reset discards, raw queue drops, disabled-writer bytes, pending
bytes and raw/metadata errors are separate. A queue acceptance means memory enqueue,
not successful disk persistence. Drops never stop capture; file write errors disable
raw recording while socket capture continues.

Optional raw recording also creates `flexray-gaps-*.jsonl`. Its `segment_start` records
associate rotated raw filenames with cumulative written offsets. `queue_full` and
`recording_disabled` records contain the missing input byte offset, size, monotonic
and realtime report times, reason and errno. A dropped chunk can split a frame.
`write_failure_queued` reports previously queued unwritten bytes; its input offset
is `18446744073709551615` (unknown, potentially discontiguous range). `written_bytes`
is cumulative across segments, not an offset within the current file. A raw write
or fsync error also makes persistence uncertain. These are host observations, not
FPGA frame timestamps. Raw wire files themselves are unchanged.

File, socket and metadata workers are independent. The metadata event queue is
bounded to 256 entries; it never waits for disk on the SPI producer. Overflow or
metadata write/fsync errors are explicitly reported, and normal close writes a
`raw_metadata_summary` with lost-event count. A missing summary, nonzero lost count
or metadata error means the sidecar is incomplete; ENOSPC can prevent recording the
loss sidecar itself. A zero metadata loss count alone does not establish complete
FPGA capture: also inspect SPI errors/pending responses and the capture exit status.
It cannot guarantee an exact loss history after disk failure
or abrupt process/power termination.

### FPGA logging diagnostics on physical CAN (0x1FA)

This is **physical CAN**, not the SPI FlexRay envelope. FPGA diagnostics retain the
physical Panda receive bus and stay on pandad's existing `can` publisher/rlog path.
No new publisher on `can`, CAN transmission, safety/control change or FlexRay-to-CAN
data collection is enabled. The separate data-collection feature stays disabled.

The wiring/Panda bus is not known yet. Confirm that the selected Panda receive bus
actually sees the FPGA CAN port, with the existing hardware/bitrate configuration.
The live monitor reports selected-bus frames, matching-ID frames and validated pages:
no selected-bus traffic is distinct from traffic without valid diagnostic messages.
This software cannot prove physical wiring, FPGA bitstream deployment or bus ACKs.
A source/DBC search found no pre-existing 0x1FA definition/TX/RX in the current
Land Rover implementation. Honda/Acura use it for BRAKE_COMMAND/LEGACY_BRAKE_COMMAND;
Hyundai CAN-FD defines ID506 with DLC32. Actual bus usage is still unknown because
the FPGA/Panda wiring is unspecified. Do not interpret every bus's 0x1FA as FPGA diagnostics. `Event.can` exposes numeric address, source and
bytes, but not the CAN IDE flag; an extended frame with the same small numeric ID
cannot be distinguished at this layer. Verify standard 11-bit framing on hardware.

Select a physical Panda bus **0..3**, not SPI sources 4/6. The following uses bus 0
only as an example, **not as a detected wiring choice**:

```bash
cd /data/openpilot
python3 -m openpilot.system.flexray_logd.diagnostics --bus 0
python3 -m openpilot.system.flexray_logd.diagnostics --bus 0 --rlog /path/to/rlog.zst
```

For automatic read-only monitoring alongside the managed FlexRay publisher, set
`FlexrayDiagnosticBus` after building the updated Params library:

```bash
python3 -c 'from openpilot.common.params import Params; Params().put("FlexrayDiagnosticBus", 0, block=True)'
```

The default is **-1** (disabled); set -1 to disable again. Bus configuration takes
effect on the next FlexRay publisher start (offroad/onroad or its menu toggle).
Normal loggerd conditions still apply. The monitor only subscribes to CAN; pandad
retains ownership. Its report continues during SPI reconnect retries.

Each 8-byte diagnostic frame has byte0 **0x20..0x27** (version 2 plus page),
byte1 an 8-bit snapshot sequence, and **six packed snapshot bytes in bytes2..7**.
There are no reserved payload bytes. Version 1 is rejected. All eight pages form
one 48-byte snapshot, decoded as `struct.unpack('<12I', snapshot)`; a uint32 can
cross a CAN-page boundary. No individual page is decoded as one uint32.

The FPGA takes one snapshot per 80,000,000 clocks at 80 MHz (1 Hz), then queues
its eight statistics pages sequentially, followed by one firmware identity record:
**9 records enqueued/s** (8 statistics + 1 identity), not simultaneous arrivals.
Actual reception can be lower due to queue full/expiry or bus conditions. Earlier
FPGA bitstreams can omit identity records while continuing to send statistics.
The first sequence after reset is 0; sequence wraps 255→0.

| Item | Snapshot bytes | Value |
| --- | --- | --- |
| 0 | 0..3 | DADC CRC-valid input frames, saturating uint32 |
| 1 | 4..7 | BCM-side CRC-valid input frames, saturating uint32 |
| 2 | 8..11 | DADC frame-queue-full drops, saturating uint32 |
| 3 | 12..15 | BCM-side frame-queue-full drops, saturating uint32 |
| 4 | 16..19 | DADC queue peak low16; BCM-side queue peak high16 |
| 5 | 20..23 | Log byte FIFO current usage, bytes |
| 6 | 24..27 | Log byte FIFO maximum usage since reset, bytes |
| 7 | 28..31 | Byte FIFO full-state entries, saturating uint32 |
| 8 | 32..35 | DADC wire input demand, wrapping uint32 bytes |
| 9 | 36..39 | BCM-side wire input demand, wrapping uint32 bytes |
| 10 | 40..43 | Valid log bytes taken by SPI prefetch, wrapping uint32 |
| 11 | 44..47 | Completed 8-bit SPI transfers, including padding, wrapping uint32 |

Frame and input-demand counters include CRC-valid frames dropped by full frame
queues, and exclude CRC-invalid frames. Input-demand bytes are payload+12 per
frame, not FlexRay physical bus occupancy. Items0..3/7 saturate at 0xFFFFFFFF;
items8..11 wrap modulo 2^32. Queue peaks are currently 0..32 slots per direction,
with the active logger request separate; the host does **not** impose 32 as a wire
validation bound because HDL generics can change queue depth. FIFO capacity is
131072 bytes excluding its separate prefetch byte. All counters and maxima reset
with the FPGA. FIFO/queue maxima are peaks, not current queue occupancy.

Item10 is valid prefetch activity, excluding empty-FIFO padding. CS interruption
and retry can leave prefetch a few bytes ahead of completed wire transfers; it is
**not USB/host delivery acknowledgement**. Item11 counts the SPI_SLAVE DOUT_VLD
completed-byte indication, includes valid bytes and zero padding, and excludes
partial CS transfers. The stated FPGA RX completion/CS-edge improvement preserves
the wire/diagnostic layout; deployment and external I/O timing are not verified here.

Diagnostic CAN uses the existing async queue and may itself be lost on full or expiry
(default lifetime 1 s). Its failure does not block SPI. These pages contain no counters
for CAN TX success/ACK errors or diagnostic queue drops. The host's validated SPI
frames and the FPGA's RX input counters therefore describe different stages.

The monitor validates selected bus, numeric ID, DLC, version2 and page0..7; mask0xFF
is required before decoding the 48-byte snapshot. FIFO range/consistency is checked
on the assembled values, not on arbitrary six-byte chunks. A 1.5 s assembly window
and retired-sequence quarantine isolate expired pages. Reordering is allowed,
identical duplicates ignored, conflicting duplicates invalidate the assembly.
Older assemblies do not replace newer complete values; a backward sequence needs
two successive complete snapshots before accepting a possible new epoch. Sequence
alone cannot distinguish reset, 256-snapshot wrap or delayed traffic. Indistinguishable
same-sequence resets inside the window cannot be conclusively identified. Ambiguity,
conflicts and expired pages are not presented as fresh complete state.

A summary is emitted immediately on complete assembly and periodically while waiting/stale.
Reports expose last-complete age, assembly mask/sequence, pending masks/ages,
reset/reordering ambiguity, monotonic counter/peak decreases and saturated event
counters. Age is host time since receipt of the final page, not FPGA snapshot time.
Freshness is 2.5 s by default; a newer partial/expired or suspected-reset assembly
keeps `latest_state_complete` false. Last complete values remain explicitly labelled
historical, and rate fields become unconfirmed for incomplete/stale latest state.

### Observed FPGA firmware identity (0x2F)

On the same explicitly selected physical CAN bus, standard numeric ID0x1FA/DLC8,
byte0 **0x2F** is processed before the statistics branch. Bytes1/2/3 are independent
uint8 major/minor/patch; bytes4..7 are a little-endian uint32 manual build number.
`2F 01 00 00 01 00 00 00` reports **FPGA firmware 1.0.0 / build 1**. This is the new
release identifier, not a host default: before actual receipt the summary says
**unknown**. The CAN diagnostic format remains version2 (byte0 high nibble),
independent of firmware major. Byte1 is never a sequence on this record.

The identity record does not enter the statistics mask, sequence tracking or rate
calculation. Statistics0x20..0x27 still assemble exactly 8*6=48 bytes/<12I; reserved
selectors0x28..0x2E and unsupported format versions remain rejected. The monitor
emits an identity observation immediately and retains the last version/build and
host receipt time for that selected bus. At **3 seconds or more** without identity
receipt it is **stale**, with last values/time retained. A delayed older timestamp
cannot overwrite a newer observation. Missing/duplicate identity records do not
stop statistics; older FPGA firmware can leave identity unknown indefinitely.

The first identity observation establishes a value without interrupting in-progress
statistics. An observed change of any major/minor/patch/build field clears pending
statistics, sequence/retired state, last complete snapshot, and throughput baseline.
Statistics stamped before that change cannot join the new epoch. The next complete
snapshot establishes a new baseline; a subsequent valid complete snapshot can
produce rates. Identical identity repeats refresh last-seen without clearing
statistics. Reset with the same identity remains possible; existing counter-reset,
sequence-wrap and ambiguity handling still applies.

This CAN observation is what the reporting bitstream embeds. The manually assigned
build ID is **not a Git hash**, automatic identification of every local source change,
or cryptographic proof of source/bitstream agreement. The new HDL is reported as
locally updated separately; until the board is programmed with it, the new identity
record will not be produced. Host tests do not verify board programming or receipt.

The optional DBC gates firmware major/minor/patch/build on full selector47 only.
Sequence signals are individually gated to statistics selectors32..39, so firmware
major is never displayed as a snapshot sequence. All original CAN bytes/bus remain
on pandad's existing CAN/rlog path.

### Interpreting logging throughput and SPI margin

Rates use the **1 Hz snapshot sequence interval**, not the spacing of eight CAN
page arrivals or individual FlexRay frame times. Sequence distance1..5 is accepted
only when host first-page time is positive and consistent within 1 s; larger gaps,
ambiguous epochs/reset, implausible half-range byte jumps or inconsistent timing
leave rates unconfirmed. Missing snapshots within a valid interval are counted.
These bounds are conservative interpretation policy, not additional wire fields.

Event deltas from items0/1 yield directional frames/s. A saturated event counter
makes its event rate unconfirmed; it does not saturate the independent wrapping
byte counters. For items8..11, each delta is `(new-old)&0xFFFFFFFF`:

- Input demand = `(delta8 + delta9) / dt`, byte/s.
- Valid prefetch output = `delta10 / dt`, byte/s, not confirmed USB delivery.
- Observed SPI clock service = `delta11 / dt`, byte/s, including padding.
- Observed read-pattern headroom = `(service-input)/service`, only for nonzero service.
  Negative values are retained as a deficit; zero service has no headroom fraction.
- `service-prefetch` is only approximate padding; prefetch lead can make it slightly
  negative. It is never labelled USB loss.

The **937500 byte/s** ceiling is nominal continuous 7.5 MHz/8, never a measured
service rate. USB/MPSSE/bulk gaps are reflected in item11's observed service rate.
Read-pattern changes also change that service. Low-load valid output alone cannot
estimate maximum capacity. Rates concern FPGA logging wire bytes, exclude CRC-bad
traffic, and are not FlexRay physical bus utilization.

Current and peak FIFO usage are shown as percentages of 131072. Consecutive observed
input deficits and FIFO-growth intervals are counted; increasing drop counters are
direct evidence of loss. Sustained input above observed service or growing FIFO
supports an inability to keep up under those conditions. One interval or one load
profile cannot establish capacity for all traffic bursts or driving conditions.

[The optional diagnostic DBC](dbc/examples/fpga_logging_diagnostics.dbc) gates the full
byte0 on decimal32..39 for statistics and decimal47 for firmware identity. It
displays statistics sequence/raw six-byte chunks and separately gated firmware fields. It cannot reconstruct cross-page uint32 fields or evaluate throughput;
use the Python assembler/live/offline summary. Apply it only to the selected physical
CAN source. Existing vehicle DBCs and FlexRay cycle rules are unchanged. If that
source already has a vehicle DBC, add the message to a local copy only after checking
ID conflicts rather than replacing the existing definitions.

### Native capture startup diagnostics (C3X/C4)

The Python publisher drains native stderr asynchronously into `cloudlog`, which
`logmessaged` forwards through `logMessage` into rlog. Reports retain the child
PID/exit code, initialization stages, native/library error codes, POSIX errno,
first error and final stderr tail. The drain thread uses bounded lines and queues;
frequent output is summarized and suppressed-line counts are reported. A short
exit is drained through EOF before its final report. Native stdout and the capture
socket remain separate. Capture state reports distinguish `starting`,
`running-with-data`, `waiting-for-data`, `retrying`, and `stopped`; they include
last observed successful read/frame times, ages and actual errors. Retry reports
include the retry count. An empty heartbeat or manager's running flag does not
confirm USB reads or valid FlexRay frames. USB read time is a host observation,
not the FPGA frame's physical arrival time.

Default selection is **0403:6011 / FT4232H / Interface B / mode 0 / 7500000 Hz**.
The native stages distinguish probe, serial selection, interface, USB open/claim,
MPSSE setup/reset/purge, GPIO response, clock, loopback, and first successful bulk
read. Device reports include serial, USB bus/address/port path, FTDI type and
interface. Multiple matching adapters require `FLEXRAY_FTDI_SERIAL` in the
manager's environment; no matching serial fails rather than claiming another
adapter. Legacy 0403:6010 Fast Serial requires explicit
`FLEXRAY_FTDI_PRODUCT=6010`; it is no longer silently preferred or used as fallback.
For standalone capture, for example:

```bash
FLEXRAY_FTDI_SERIAL=YOUR_SERIAL ./openpilot/system/flexray_logd/flexray_logd
```

Stop the managed collector first; only one process may claim Interface B. Kernel
driver detach refers to that interface and is distinct from cable disconnection.
No whole-device USB reset or blanket driver unbind is added. GPIO queries request
immediate response and wait up to a total 300 ms, including delayed/status-only
reads, without issuing a second query while a response is pending. A consumed
but mismatched GPIO response permits a bounded re-query; fatal errors, incomplete
command writes and deadline expiry fail visibly. This fixes a code weakness; it
does **not** establish the cause of the previously observed C3X failure.

In the investigated vehicle, FPGA firmware 1.0.0/build 1 was observed on **Panda
CAN bus 1**. Configure it explicitly on that vehicle:

```bash
python3 -c 'from openpilot.common.params import Params; Params().put("FlexrayDiagnosticBus", 1, block=True)'
```

Restart the FlexRay publisher to load the setting. Default **-1 disables CAN
monitoring**; do not assume bus 1 on other installations. CAN monitoring continues
while native capture retries. Two consecutive valid measurement intervals with
positive input demand, a full FIFO and zero SPI-completed-byte growth report
`SPI 읽기 미진행` (SPI read not progressing). Zero service is not evidence that
7.5 MHz bandwidth is insufficient. Missing/stale/ambiguous snapshots remain
unknown; the firmware identity and eight statistics pages retain their formats.

Hardware recheck remains required after installing the local changes: confirm
`configured_clock=7500000`, increasing USB payload and FPGA SPI completed bytes,
FIFO recovery, and source 4/6 frames in rlog. Then compare actual service, input,
FIFO growth and drops (the investigated input was about 276080 wire bytes/s).
Host mocks do not verify C3X USB permissions, wiring, bitstream programming,
board timing, device removal, or actual sustained throughput.

### FlexRay board compatibility and receive indicator

For the selected **0403:6011 / Interface B** capture board, the reader now applies
an explicit `flexray_6011_h` SPI profile. This restores the working legacy
`8A 97 8D 85` MPSSE initialization and 7.5 MHz mode 0 even when libftdi reports
`TYPE_BM`, as observed on C3X. The detected type is preserved and logged separately;
the profile supplies SPI capabilities to both initialization and clock division.
Automatic generic FTDI handling and explicit 6010 Fast Serial selection retain
their existing behavior. Serial filtering, unique-device selection, real setup
error checks and bounded GPIO/stream waits still apply. USB enumeration and this
profile do not by themselves prove that the board is receiving valid frames.

The collector automatically runs read-only `lsusb -v -d 0403:6011` once at publisher
startup in a separate worker. Command, return code, combined stdout/stderr,
timeout and truncation are recorded as `FlexRay USB descriptor` cloudlog records,
forwarded through `logMessage` into rlog (and the normal device log files).
The worker has a five-second deadline and retains at most 32768 output bytes;
excess output is drained and counted. A missing command or permission failure is
recorded without stopping capture. Native logs also record bcdDevice, USB speed
code, detected FTDI type, endpoint packet size and the selected board profile.
No separate user-run lsusb command is required before trying the update.

In **Settings → Toggles**, **Show FlexRay Receive Status** is immediately below
**Record FlexRay Data**. Its persistent default is enabled. The setting is also
available in the C4 settings layout. Turning the indicator off affects only the
screen; collection, CAN diagnostics and rlog recording continue unchanged.

The driving-screen indicator shows:

- Green **Receiving data**: a source 4/6 frame has actually been published within
  the last two seconds, with per-source frames/s measured over host intervals.
- Yellow **Waiting for data**: capture is active but valid FlexRay frames are absent.
- Blue **Starting**: initialization is in progress.
- Red **Retrying connection**: the native collector failed; the retry count is shown.
- Gray **Logging disabled / Stopped** or orange **Status unavailable** as applicable.

USB padding, empty heartbeats, manager `running=true` and physical CAN diagnostic
records alone never produce the green indication. Telemetry older than three
seconds is unavailable, and previous-trip messages do not keep the indication
alive. A green indicator confirms host reception/publication, not a disk-write
acknowledgement or the physical arrival time of each frame. Full-screen driving
alerts take priority over the indicator.

A separate low-rate `flexrayStatus` service records capture activity, source 4/6
counts/rates, native read/frame timestamps, retry count and last error in rlog.
It uses a reserved fork metadata slot; FlexRay frames remain standard `Event.can`
on `flexray` with original IDs and sources 4/6. pandad still owns physical `can`.

For a clean test-route finish, park and disengage, then use the sunnypilot Device
panel's **Enable Always Offroad** (or switch off ignition/ACC). Wait for the home
screen and allow about 30 seconds with power maintained before disconnecting or
copying the completed logs. **Exit Always Offroad** resumes normal onroad startup.
The delay allows recording to finish; it is not a substitute for the offroad
transition. Actual C3X/C4 operation and SPI throughput still require device tests.

### Follow-up from the C3X route (nonstandard USB revision and startup recording)

The captured USB descriptors confirmed **0403:6011**, four interfaces, 512-byte
Bulk endpoints on Interface B and **bcdDevice 36.00 (`0x3600`)**. The bundled
libftdi only recognized the factory FT4232H revision `0x0800`; the unmatched
revision left its initial `TYPE_BM` value unchanged. That value was a fallback,
not a positive identification of BM hardware. Native logs now distinguish an
unmatched descriptor from the applied `flexray_6011_h` profile. The USB descriptor
revision is separate from FPGA CAN firmware identity 1.0.0/build 1.

Successful native calls no longer report leftover errno as a failure. Structured
`flexray_stats` records are interpreted as statistics, so a field named
`raw_failed_bytes` with value zero cannot populate the last-error field. Real
negative returns, short command writes and explicit failure records remain visible.

The receive indicator is now at the **lower left**, above the driver icon and
bottom developer bar. It reserves space for the right developer column in narrow
camera views and for small/medium alerts; full-screen alerts still take priority.
The `/s` numbers are **valid host-received frames per second for each source**,
not cumulative counts, USB bytes/s, physical bus occupancy or disk acknowledgements.
Rate calculation uses arrivals independently of delayed startup publication, so
flushing buffered frames does not inflate the receive rate.

The complete route also exposed a fixed initial gap of 6197 frames between
publisher totals and rlog, with no subsequent growth. Capture began before the
recorder had consumed data. The startup path now retains serialized CAN events
with original host timestamps in a **4 MiB bounded buffer** while continuing to
read and decode SPI. Only after loggerd writes an invalid empty `flexray` probe
from this publisher to the active route does its acknowledgement unlock frame
publication. Probes stay on the private FlexRay transport and never transmit CAN
on the vehicle. Old acknowledgements cannot unlock a new publisher's probe.

Flushing is bounded per iteration; a slow or unavailable recorder does not pause
SPI capture. Full-buffer and shutdown-before-ready losses are reported separately
with frame/byte totals, time and reason. The indicator displays **Preparing
recording** while valid frames await recorder readiness. `flexrayStatus` records
`loggerReady`, startup buffered/dropped frame and byte counts, host received totals
(`src4ReceivedFrames`/`src6ReceivedFrames`) and published totals (`src4Frames`/
`src6Frames`). Startup byte totals count serialized Event bytes, including message
overhead; they are separate from FPGA wire-byte and USB payload counters.
The readiness acknowledgement is not a per-frame durability ACK;
it does not guarantee against recorder failure after startup. This change does
not enable offroad acquisition or change the existing logging/control conditions.

Host validation includes starting the actual loggerd after frames have already
arrived, then verifying complete ordered rlog preservation, including 259-byte
CAN bodies, rejection of old ACKs, bounded overflow/shutdown accounting, and stable
arrival rates across a delayed flush. Device confirmation of the startup fix and
physical screen placement remains required after rebuilding the updated binaries.

The review also hardens reported IPC send failures: data remains queued until a
send succeeds, published totals advance only on success, and a fresh probe is
required after transport failure. Probe/ACK read errors are reported with bounded
frequency while SPI capture continues. Shutdown flushing has a one-second deadline
and accounts for any remaining backlog; cleanup also runs on an unexpected parent
exception. `lastError` reflects the latest reported native error, while the first
native error remains available in the bounded stderr diagnostic record. Repeated
unchanged native history does not overwrite a newer transport error.
Loggerd also reports a failed readiness-parameter write with its return code and
errno rather than silently leaving the collector waiting for acknowledgement.

Readiness is a startup/subscription check. A writer killed after acknowledgement,
a later disk failure or a transport that silently loses data still requires
separate monitoring; the acknowledgement is not a per-frame persistence protocol.
FPGA frames dropped before host acquisition starts cannot be recovered by this
host startup buffer. Verify the startup published-versus-recorded counts and the
new lower-left placement on C3X after updating.
