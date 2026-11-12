# 🔐 Safety & Legal Disclaimer
 This repository is for research and development only.
 Use in live vehicles must comply with local laws and safety standards.
 Any damage or consequences are at the user’s responsibility.

<br><br>
# 🚘 This branch adds LAND ROVER vehicles to Sunnypilot.
This README describes **`lrmaster-SP-flexraylog-v2-tici`**, the C3 (comma three)
FlexRay v2 port based on `lrmaster-SP-tici` (`8caeca71df`), with capture code
ported from `lrmaster-SP-flexraylog-v2` (`34a9b50b9d`). It retains the C3 base's
openpilot **0.10.1**, AGNOS **12.8**, Land Rover/Panda configuration and exact
submodule commits. It does not merge the C3X/C4 master platform or its safety IDs.

| Branch | Target |
| --- | --- |
| `lrmaster-SP-flexraylog-v2-tici` | C3 FlexRay v2 port described here; clone command below |
| `lrmaster-SP-tici` | Existing C3 base |
| `lrmaster-SP` | C3X/C4 Land Rover master integration |
| `lrmaster-SP-flexraylog-v2` | C3X/C4 FlexRay v2 |
| `lrmaster-SP-flexraylog` | Legacy pandad-based FlexRay implementation |

### Installation

Back up an existing installation before using `/data/openpilot` as a clone target.
Clone this branch from the Land Rover fork:

```bash
cd /data
git clone --recurse-submodules --branch lrmaster-SP-flexraylog-v2-tici https://github.com/dolson8874/sunnypilot.git openpilot
cd /data/openpilot
scons -j8
```

Do not update submodules with `--remote`. Use the exact pointers recorded here.
This is a host-validated port; C3 camera/model/Panda/USB operation and vehicle
behavior must be confirmed on the actual device before claiming device support.

### FlexRay v2 logging on C3

Settings → Toggles → **Record FlexRay Data** defaults to enabled and applies
immediately. Acquisition follows loggerd's onroad condition, including passive /
dashcam operation; engagement is not required. Offroad acquisition is not enabled.
**Show FlexRay Receive Status** controls only the display. The Qt indicator is at
the lower left, above the driver icon and bottom developer bar; it is hidden
while a driving alert is displayed. Source 4/6 numbers mean actual frames/second.

The independent collector is in `system/flexray_logd`, launched by `flexrayd.py`.
The legacy collector and virtual FTDI Panda code remain in the source but are
inactive so only v2 acquires the adapter. Pandad alone publishes vehicle `can`;
v2 publishes standard `Event.can` on `flexray`. Loggerd preserves it in rlog,
with a bounded 4 MiB startup buffer until the route writer acknowledges a probe.
The acknowledgement is not a per-frame disk durability guarantee.

CA A0 maps DADC→BCM-side to bus 2 / source 6; CA 80 maps BCM-side→DADC to bus 0 /
source 4. IDs and flags/cycle/payload/CRC24 remain intact. Cabana supports 259-byte
bodies, both live channels and cycle multiplexing (cycle at bit 8, payload at bit
16). The source offset of 4 assumes one physical Panda; revisit before using
multiple Pandas. No control or physical CAN transmit feature is enabled here.

FT4232H 0403:6011 Interface B uses mode 0 and 7.5 MHz. The explicit board profile
preserves the known descriptor fallback handling; 10 MHz remains unverified.
Multiple adapters require `FLEXRAY_FTDI_SERIAL`. Native stderr, USB descriptors,
queue losses and receive health are recorded through cloudlog/rlog.

`FlexrayDiagnosticBus` defaults to **-1** (disabled). Configure the actual Panda
bus explicitly, for example `Params().put('FlexrayDiagnosticBus', 1)` from the
repository Python environment. Observed bus 1 on C3X is not proof of C3 wiring.
Read-only physical CAN 0x1FA diagnostics retain packed v2 statistics and separate
0x2F firmware identity; unknown/stale/reset/wrap and rate semantics are preserved.

No `FLEXRAY_LOG_DIR` is needed for rlog. It enables only an optional raw dump to
an existing writable directory. Queue/file failures do not stop SPI capture.

Host verification commands:

```bash
make -C system/flexray_logd all test
pytest system/flexray_logd/tests/test_diagnostics.py system/flexray_logd/tests/test_flexrayd.py system/flexray_logd/tests/test_startup.py system/flexray_logd/tests/test_status.py
scons system/flexray_logd/flexray_logd system/loggerd/loggerd selfdrive/pandad/pandad selfdrive/ui/ui
```

<br><br><br><br>


![](https://user-images.githubusercontent.com/47793918/233812617-beab2e71-57b9-479e-8bff-c3931347ca40.png)

## 🌞 What is sunnypilot?
[sunnypilot](https://github.com/sunnyhaibin/sunnypilot) is a fork of comma.ai's openpilot, an open source driver assistance system. sunnypilot offers the user a unique driving experience for over 300+ supported car makes and models with modified behaviors of driving assist engagements. sunnypilot complies with comma.ai's safety rules as accurately as possible.

## 💭 Join our Discord
Join the official sunnypilot Discord server to stay up to date with all the latest features and be a part of shaping the future of sunnypilot!
* https://discord.gg/sunnypilot

  ![](https://dcbadge.vercel.app/api/server/wRW3meAgtx?style=flat) ![Discord Shield](https://discordapp.com/api/guilds/880416502577266699/widget.png?style=shield)

## Documentation
https://docs.sunnypilot.ai/ is your one stop shop for everything from features to installation to FAQ about the sunnypilot

## 🚘 Running on a dedicated device in a car
* A supported device to run this software
    * a [comma three](https://comma.ai/shop/products/three) or a [C3X](https://comma.ai/shop/comma-3x)
* This software
* One of [the 300+ supported cars](https://github.com/commaai/openpilot/blob/master/docs/CARS.md). We support Honda, Toyota, Hyundai, Nissan, Kia, Chrysler, Lexus, Acura, Audi, VW, Ford and more. If your car is not supported but has adaptive cruise control and lane-keeping assist, it's likely able to run sunnypilot.
* A [car harness](https://comma.ai/shop/products/car-harness) to connect to your car

Detailed instructions for [how to mount the device in a car](https://comma.ai/setup).

## Installation
Please refer to [Recommended Branches](#-recommended-branches) to find your preferred/supported branch. This guide will assume you want to install the latest `staging-tici` branch.

### If you want to use our newest branches (our rewrite)
> [!TIP]
>You can see the rewrite state on our [rewrite project board](https://github.com/orgs/sunnypilot/projects/2), and to install the new branches, you can use the following links

* sunnypilot not installed or you installed a version before 0.8.17?
  1. [Factory reset/uninstall](https://github.com/commaai/openpilot/wiki/FAQ#how-can-i-reset-the-device) the previous software if you have another software/fork installed.
  2. After factory reset/uninstall and upon reboot, select `Custom Software` when given the option.
  3. Input the installation URL per [Recommended Branches](#-recommended-branches). Example: ```https://staging-tici.sunnypilot.ai```.
  4. Complete the rest of the installation following the onscreen instructions.

* sunnypilot already installed and you installed a version after 0.8.17?
  1. On the comma three, go to `Settings` ▶️ `Software`.
  2. At the `Download` option, press `CHECK`. This will fetch the list of latest branches from sunnypilot.
  3. At the `Target Branch` option, press `SELECT` to open the Target Branch selector.
  4. Scroll to select the desired branch per  Recommended Branches (see below). Example: `staging-tici`


|     Branch      |               Installation URL                |
|:---------------:|:---------------------------------------------:|
| `staging-tici`  |     `https://staging-tici.sunnypilot.ai`      |
| `custom-branch` | `https://install.sunnypilot.ai/{branch_name}` |
| `release-tici`  |            **Not yet available**.             |

> [!TIP]
> You can use sunnypilot/targetbranch as an install URL. Example: 'sunnypilot/staging-tici'.

> [!NOTE]
> Do you require further assistance with software installation? Join the [sunnypilot Discord server](https://discord.sunnypilot.com) and message us in the `#installation-help` channel.


<details>

<summary>Older legacy branches</summary>

### If you want to use our older legacy branches (*not recommended*)

> [**IMPORTANT**]
> It is recommended to [re-flash AGNOS](https://flash.comma.ai/) if you intend to downgrade from the new branches.
> You can still restore the latest sunnylink backup made on the old branches.

|    Branch    |         Installation URL         |
|:------------:|:--------------------------------:|
| `release-c3` | https://release-c3.sunnypilot.ai |
| `staging-c3` | https://staging-c3.sunnypilot.ai |
|   `dev-c3`   | https://dev-c3.sunnypilot.ai     |

</details>


## 🎆 Pull Requests
We welcome both pull requests and issues on GitHub. Bug fixes are encouraged.

Pull requests should be against the most current `master` branch.

## 📊 User Data

By default, sunnypilot uploads the driving data to comma servers. You can also access your data through [comma connect](https://connect.comma.ai/).

sunnypilot is open source software. The user is free to disable data collection if they wish to do so.

sunnypilot logs the road-facing camera, CAN, GPS, IMU, magnetometer, thermal sensors, crashes, and operating system logs.
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
