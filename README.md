# 🔐 Safety & Legal Disclaimer
 This repository is for research and development only.
 Use in live vehicles must comply with local laws and safety standards.
 Any damage or consequences are at the user’s responsibility.

<br><br>
# 🚘 This repository adds LAND ROVER vehicles to sunnypilot.

This README describes **`test/lrmaster-SP-flexraylog-v2-wip`**, the C3X/C4 work-in-progress branch with standalone FlexRay capture, selected DADC original logging (source 5), and read-only cruise/radar analysis observations.
`lrmaster-SP` supplies the master integration; the release-based FlexRay branch remains separate.
The pinned upstream master is **`3d8f211d4b2d7c4a981633783232c8ff8dbe402b`**
(sunnypilot **2026.003.000**, openpilot **0.11.3**).
The [C3 TICI WIP](https://github.com/dolson8874/sunnypilot/tree/test/lrmaster-SP-tici-wip) has its own installation instructions.

| Published branch | Purpose |
| --- | --- |
| `lrmaster-SP` | Land Rover upstream-master integration for C3X and C4 |
| `test/lrmaster-SP-wip` | Defender WIP with CAN logging for C3X and C4 |
| `test/lrmaster-SP-tici-wip` | C3 WIP with Range Rover Vogue 2017 support |
| `lrmaster-SP-tici` | C3 base branch |
| `lrmaster-SP-flexraylog` | Legacy FlexRay implementation integrated with pandad |
| `lrmaster-SP-flexraylog-v2` | Separate master-based FlexRay capture branch for C3X and C4 |
| `test/lrmaster-SP-flexraylog-v2-wip` | This branch: FlexRay source 4/5/6 logging and read-only analysis observations for C3X and C4; clone command below |

### First install on C3X or C4

This branch targets **C3X or C4** with **AGNOS 19.9**. Run these commands in an offroad device shell with internet access. The device launcher uses `/data/openpilot`. Back up and move an existing installation out of that path before cloning. For an existing checkout of this WIP, use the update methods below.

```bash
cd /data &&
test ! -e openpilot && test ! -L openpilot &&
git clone --branch test/lrmaster-SP-flexraylog-v2-wip --recurse-submodules https://github.com/dolson8874/sunnypilot.git openpilot &&
cd /data/openpilot &&
git log -1 --oneline --decorate &&
git submodule status --recursive
```

After the clone succeeds, reboot the device while offroad and allow the first startup build to finish. The launcher runs SCons when the checkout has no `prebuilt` marker.

### Update from the device screen

On an existing WIP installation, open **Settings → Software** while offroad and connected to the internet.

1. Check that the target branch is **`test/lrmaster-SP-flexraylog-v2-wip`** and that the installed repository's `origin` points to `dolson8874/sunnypilot`.
2. Select **Check for update**. When an update is available, select **Download update** and wait for the install option.
3. Select **Install** (or **Install now**) and allow the device to reboot and finish its startup build. Check the branch and commit shown in **Software** afterward.

The updater fetches the selected branch, cleans its staging copy and checks out the recorded submodule commits recursively. This also removes an untracked `prebuilt` marker from the staged WIP checkout. The screen update handles these steps without separate shell commands. Back up any local source edits before using it.

If `DisableUpdates` is set to `1`, the updater exits at startup. To use the screen updater, turn off **Disable Updates** where that setting is available and reboot. To keep updates disabled, use the manual method below.

### Switch from the previous WIP branch

On a device still running `lrmaster-SP-flexraylog-v2-wip`, select `test/lrmaster-SP-flexraylog-v2-wip` once as the target branch in **Settings → Software**, then download and install the update. SSH users can switch from a clean checkout and then follow the usual shell update steps.

```bash
cd /data/openpilot &&
git fetch origin refs/heads/test/lrmaster-SP-flexraylog-v2-wip:refs/remotes/origin/test/lrmaster-SP-flexraylog-v2-wip &&
git switch --track origin/test/lrmaster-SP-flexraylog-v2-wip
```

### Update an existing WIP checkout from the shell

While offroad, run `git -C /data/openpilot status --short --branch` and `git -C /data/openpilot remote get-url origin`. Confirm the WIP branch and fork, and preserve any local edits, including edits in submodules, before continuing.

```bash
cd /data/openpilot &&
test "$(git branch --show-current)" = "test/lrmaster-SP-flexraylog-v2-wip" &&
git pull --ff-only origin test/lrmaster-SP-flexraylog-v2-wip &&
git submodule sync --recursive &&
git submodule update --init --recursive &&
git log -1 --oneline --decorate &&
git -C opendbc_repo log -1 --oneline &&
git submodule status --recursive
```

A different branch stops the command chain before the pull. If Git reports that a fast-forward is impossible, inspect the local commits with `git status -sb` and `git log --oneline --left-right HEAD...origin/test/lrmaster-SP-flexraylog-v2-wip`. A leading space in each submodule status line means it matches the recorded commit. A leading `-`, `+` or `U` indicates an uninitialized submodule, a different commit or a conflict respectively.

For a manual update that changes native code, Params keys or message schemas, run the following **after the update succeeds**. The Blendful lane preference update is one such change.

```bash
cd /data/openpilot && rm -f -- ./prebuilt && sudo reboot
```

This removes the build-skip marker so the launcher performs its normal incremental build. Quickboot can recreate the marker after startup. A routine source update does not require `scons -c`.

### Cruise analysis and branch integration

Cruise analysis summaries are **off by default**. Use the full `rlog` for offline analysis of
raw CAN, FlexRay sources 4/5/6, steering state and commands, model output and IMU data.
For an on-device diagnostic session, enable **Record cruise analysis summaries** in the Developer
settings while offroad. **Cruise analysis raw display** controls the optional overlay separately.
The enabled observer writes bounded summaries to its 2MiB service. When disabled it consumes no
CAN or FlexRay messages and generates no summaries. Raw FlexRay capture uses **Record FlexRay Data**.

`--recurse-submodules` checks out the exact submodule commits recorded by this branch.
Do not use `git submodule update --remote` to prepare a matching device checkout.
When integrating an upstream release, merge and publish the forked `panda` and `opendbc_repo`
commits first, then record their new pointers here. The commits must be reachable from the URLs in `.gitmodules`.
This branch integrates upstream master directly; it does not merge the release stabilization history first.
Source packages now live under `openpilot/`; use the repository root for SCons and dependency setup.
The upstream default AGNOS version is **19.9**. Actual comma-device and vehicle validation remains required.

Land Rover uses safety model **39** because upstream uses **35 for BYD**, **36 for Volvo**,
**37 for BMW**, and **38 for MG**. Upgrade the application and Panda firmware together.
Regenerate CarParams using the normal startup/fingerprinting process; do not reuse legacy Land Rover safety ID 35.
Pandad rejects a legacy Land Rover configuration that would otherwise select BYD safety.

The existing Land Rover disabled-angle and real-time safety test failures remain deferred.
This integration preserves the current steering limits and adapts the upstream schema/model APIs;
it does not apply the separately recorded functional improvements.
The release integration branches are retained locally for comparison and rollback;
they are not published clone targets on GitHub.

### FlexRay capture

FlexRay logging is **enabled by default**. In **Settings → Toggles → Record FlexRay Data**, switch capture on or off.
The choice is saved across reboots and takes effect without restarting sunnypilot.
Capture runs with loggerd while the device is onroad, including dashcam mode; engagement is not required.
A connected FTDI/FPGA capture board is required. If unavailable, capture retries every five seconds.

The managed publisher owns the capture subprocess and sends standard `Event.can` messages on a separate `flexray` logging channel.
Loggerd records full frames in the normal driving route's **rlog**; qlog does not contain these frames.
**No `FLEXRAY_LOG_DIR` setting is needed for normal logging.**
Car CAN traffic remains on the existing `can` service, owned by pandad; FlexRay never publishes on that channel.
The `flexray` channel is a logging-only transport: its channel name intentionally differs from its `can` event type.
Consumers must use raw socket subscriptions, not `SubMaster(["flexray"])`.
The source offset is 4 (`PANDA_BUS_OFFSET`) because this branch's pandad handles one Panda.
Revisit the offset before adding support for multiple Pandas.

Cabana reads the saved frames through its existing CAN event path and subscribes to both channels for device streaming. To distinguish FlexRay from car CAN,
FlexRay frames retain source **4 + received bus**. The accepted wire markers are **CA A0**
(DADC → BCM-side, bus 2 → source **6**), **CA 80** (BCM-side → DADC, bus 0 → source **4**),
and **CA 90** (selected DADC originals, bus 1 → source **5**). Source 5 preserves all cycles
of FPGA-selected IDs 0x1F/0x31/0x0D, whether or not the output payload was changed.
It requires the compatible FPGA source5 implementation; firmware 1.0.0/build1 alone does not identify support.
Original counts and wire bytes are reported separately in native flexray_stats. They do not measure FPGA original-queue drops.
Source5 is recorded in rlog/Cabana and does not feed the existing source6 cruise observer.
DADC logs represent the FPGA's modified forwarding output. BCM-side identifies a bus segment,
not a guarantee that the BCM ECU alone transmitted the frame. Both directions preserve the original frame ID.
Frame IDs remain unchanged. The old ID/counter classification is retained but disabled;
use Cabana's DBC Multiplexor to classify cycles.
Capture reports per-direction frames/wire bytes, bulk bytes, padding/noise, CRC/metadata errors,
resynchronizations and independent queue losses once per second.
Physical CAN diagnostics at ID **0x1FA** use packed version **2** (eight 6-byte pages → 48 bytes / 12 uint32 values), separate from SPI capture. They remain on pandad's
`can` channel and require an explicitly selected Panda bus (`FlexrayDiagnosticBus`, default **-1**, disabled).
See Cabana's README for live/offline snapshot assembly, wrapping byte-counter throughput, FIFO growth and observed SPI headroom.
The 937500 byte/s continuous-clock ceiling is nominal; measured service comes from the FPGA completed-SPI-byte counter.
A separate `0x2F` CAN record reports observed FPGA firmware major/minor/patch and a manual build ID.
Identity is unknown before receipt and stale after 3 seconds; it does not change the statistics layout.
The new identifier requires the separately updated FPGA bitstream to be programmed on the board.
Native startup/error stderr is forwarded through cloudlog into rlog, with bounded output,
initialization stages, child exit status and capture activity reports. Default USB selection is
0403:6011 Interface B with an explicit legacy-compatible SPI profile; the detected FTDI type
is retained separately. Multiple adapters require `FLEXRAY_FTDI_SERIAL`, and legacy 6010
requires explicit selection. For the investigated vehicle, set `FlexrayDiagnosticBus=1`
(default -1 disables diagnostics) and recheck actual USB/SPI progress before assessing bandwidth.
**Show FlexRay Receive Status**, directly below **Record FlexRay Data**, controls an optional
onroad indicator at the lower left, clear of developer diagnostics and the driver icon.
Numbers remain source 4/6 received frames per second; source5 also refreshes receive health but is not added to those rates. Hiding the indicator does not stop logging.
Startup frames are bounded-buffered until loggerd acknowledges this publisher; startup losses are counted.
USB descriptor command results and low-rate capture status are also recorded in rlog.
See [native startup troubleshooting](openpilot/tools/cabana/README.md#native-capture-startup-diagnostics-c3xc4).
See [Cabana's FlexRay instructions](openpilot/tools/cabana/README.md#flexray-cycle-classification).

#### Optional raw dump

`FLEXRAY_LOG_DIR` is only for an additional raw byte dump alongside rlog. If used, set it to an existing writable directory
in the launcher's environment before the manager starts. Raw files are separate from sunnypilot routes and are not directly loadable as Cabana routes.

For standalone diagnostics, turn off **Record FlexRay Data** in the menu before starting another collector:

```bash
cd /data/openpilot
mkdir -p /data/flexray_logs
./openpilot/system/flexray_logd/flexray_logd -o /data/flexray_logs
```

This standalone command writes raw files and exposes the legacy socket; the manager's publisher is needed for rlog recording.
Use one collector per FTDI interface. Raw files use unique names and rotate at 64 MiB by default; `-m BYTES` changes the limit.
File replay runs once with `-f FILE`; add `-l` to loop. Run `-h` for the available options.

- Raw recording queue overflow drops the incoming batch and reports the lost bytes while capture continues.
  A separate `flexray-gaps-*.jsonl` sidecar records input offsets, sizes, times and reasons without changing raw wire files.
  Its bounded metadata queue and write failures are reported separately; missing metadata makes a recording incomplete.
- Raw file write failures disable that recording and report the cause to stderr; capture and rlog publication continue. Raw recording does not automatically restart.
- Input errors end the native capture subprocess; the managed publisher reports the error and retries.

<br><br><br><br>


![](https://user-images.githubusercontent.com/47793918/233812617-beab2e71-57b9-479e-8bff-c3931347ca40.png)

## 🌞 What is sunnypilot?
[sunnypilot](https://github.com/sunnyhaibin/sunnypilot) is a fork of comma.ai's openpilot, an open source driver assistance system. sunnypilot offers the user a unique driving experience for over 300+ supported car makes and models with modified behaviors of driving assist engagements. sunnypilot complies with comma.ai's safety rules as accurately as possible.

## 💭 Join our Community Forum
Join the official sunnypilot community forum to stay up to date with all the latest features and be a part of shaping the future of sunnypilot!
* https://community.sunnypilot.ai/

## Documentation
https://docs.sunnypilot.ai/ is your one stop shop for everything from features to installation to FAQ about the sunnypilot

## 🚘 Running on a dedicated device in a car
First, check out this list of items you'll need to [get started](https://community.sunnypilot.ai/t/getting-started-using-sunnypilot-in-your-supported-car/251).

## Installation
For this Land Rover WIP branch, use [First install on C3X or C4](#first-install-on-c3x-or-c4) above. For subsequent updates, use the [device screen](#update-from-the-device-screen) or the [device shell](#update-an-existing-wip-checkout-from-the-shell). For general upstream setup, refer to the sunnypilot community forum for [installation instructions](https://community.sunnypilot.ai/t/read-before-installing-sunnypilot/254), as well as a complete list of [Recommended Branch Installations](https://community.sunnypilot.ai/t/recommended-branch-installations/235).

## 🎆 Pull Requests
We welcome both pull requests and issues on GitHub. Bug fixes are encouraged.

Pull requests should be against the most current `master` branch.

## 📊 User Data

By default, sunnypilot uploads the driving data to comma servers. You can also access your data through [comma connect](https://connect.comma.ai/).

sunnypilot is open source software. The user is free to disable data collection if they wish to do so.

sunnypilot logs the road-facing camera, CAN, GPS, IMU, magnetometer, thermal sensors, crashes, and operating system logs.
This branch also records FlexRay frames when **Record FlexRay Data** is enabled.
The driver-facing camera and microphone are only logged if you explicitly opt-in in settings.

By using this software, you understand that use of this software or its related services will generate certain types of user data, which may be logged and stored at the sole discretion of comma. By accepting this agreement, you grant an irrevocable, perpetual, worldwide right to comma for the use of this data.

## Licensing

sunnypilot is released under the [MIT License](LICENSE). This repository includes original work as well as significant portions of code derived from [openpilot by comma.ai](https://github.com/commaai/openpilot), which is also released under the MIT license with additional disclaimers.

The original openpilot license notice, including comma.ai’s indemnification and alpha software disclaimer, is reproduced below as required:

> openpilot is released under the MIT license. Some parts of the software are released under other licenses as specified.
>
> Any user of this software shall indemnify and hold harmless Comma.ai, Inc. and its directors, officers, employees, agents, stockholders, affiliates, subcontractors and customers from and against all allegations, claims, actions, suits, demands, damages, liabilities, obligations, losses, settlements, judgments, costs and expenses (including without limitation attorneys’ fees and costs) which arise out of, relate to or result from any use of this software by user.
>
> **THIS IS ALPHA QUALITY SOFTWARE FOR RESEARCH PURPOSES ONLY. THIS IS NOT A PRODUCT.
> YOU ARE RESPONSIBLE FOR COMPLYING WITH LOCAL LAWS AND REGULATIONS.
> NO WARRANTY EXPRESSED OR IMPLIED.**

For full license terms, please see the [`LICENSE`](LICENSE) file.

## 💰 Support sunnypilot
If you find any of the features useful, consider becoming a [sponsor on GitHub](https://github.com/sponsors/sunnyhaibin) to support future feature development and improvements.


By becoming a sponsor, you will gain access to exclusive content, early access to new features, and the opportunity to directly influence the project's development.


<h3>GitHub Sponsor</h3>

<a href="https://github.com/sponsors/sunnyhaibin">
  <img src="https://user-images.githubusercontent.com/47793918/244135584-9800acbd-69fd-4b2b-bec9-e5fa2d85c817.png" alt="Become a Sponsor" width="300" style="max-width: 100%; height: auto;">
</a>
<br>

<h3>PayPal</h3>

<a href="https://paypal.me/sunnyhaibin0850" target="_blank">
<img src="https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif" alt="PayPal this" title="PayPal - The safer, easier way to pay online!" border="0" />
</a>
<br></br>

Your continuous love and support are greatly appreciated! Enjoy 🥰

<span>-</span> Jason, Founder of sunnypilot
