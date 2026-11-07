# 🔐 Safety & Legal Disclaimer
 This repository is for research and development only.
 Use in live vehicles must comply with local laws and safety standards.
 Any damage or consequences are at the user’s responsibility.

<br><br>
# 🚘 This repository adds LAND ROVER vehicles to sunnypilot.

This README describes **`lrmaster-SP-flexraylog-v2`**, the standalone FlexRay capture branch based on `lrmaster-SP`.
Device validation is still pending. The proposed `v2026.002.002` integration has not been applied to this branch yet.

| Branch | Purpose |
| --- | --- |
| `lrmaster-SP` | Land Rover base branch for C3X |
| `lrmaster-SP-tici` | Land Rover branch for C3 |
| `lrmaster-SP-flexraylog` | Legacy FlexRay implementation integrated with pandad |
| `lrmaster-SP-flexraylog-v2` | Standalone FlexRay capture with the current Panda architecture |

### Clone this branch

Back up any existing `/data/openpilot` installation before cloning into that path.

```bash
cd /data
git clone --recurse-submodules --branch lrmaster-SP-flexraylog-v2 https://github.com/dolson8874/sunnypilot.git openpilot
cd /data/openpilot
scons -j8
```

`--recurse-submodules` checks out the exact submodule commits recorded by this branch.
Do not use `git submodule update --remote` to prepare a matching device checkout.

### FlexRay capture

The manager starts `system/flexray_logd` when `FLEXRAY_LOGGING=1` is set in the launcher's environment **before the manager starts**.
It is disabled by default. Setting this variable in a separate terminal does not change an already running manager.
For optional raw recording, also set `FLEXRAY_LOG_DIR` to an existing writable directory.

Alternatively, run the standalone collector while the manager's FlexRay process is disabled:

```bash
cd /data/openpilot
mkdir -p /data/flexray_logs
./system/flexray_logd/flexray_logd -o /data/flexray_logs
```

Use one collector per FTDI interface. Raw files use unique names and rotate at 64 MiB by default; `-m BYTES` changes the limit.
File replay runs once with `-f FILE`; add `-l` to loop. Run `-h` for the available options.

- Recording queue overflow drops the incoming batch and reports the lost bytes while capture continues.
- File write failures disable recording and report the cause to stderr; capture and socket output continue. Recording does not automatically restart.
- Input device errors and SPI read timeouts still end the process with an error.

Captured frame IDs remain unchanged. The old ID/counter classification is retained but disabled; use Cabana's DBC Multiplexor for classification.
See [Cabana's FlexRay instructions](tools/cabana/README.md#flexray-cycle-classification).
The dedicated FlexRay messaging service and rlog integration are deferred: raw `.log` files are separate from sunnypilot routes and are not directly loadable as Cabana routes.

### Publishing an integrated build

When merging an upstream release, merge the forked `panda` and `opendbc_repo` histories and publish their new commits first.
Then update the parent repository's submodule pointers. Each recorded commit must be reachable from the corresponding URL in `.gitmodules`.
Merge the updated `lrmaster-SP` into this branch, resolve build dependency changes, and verify the build before publishing it.
The parent repository can publish only `lrmaster-SP-flexraylog-v2`; its referenced submodule commits must already be available for recursive cloning.

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
Next, refer to the sunnypilot community forum for [installation instructions](https://community.sunnypilot.ai/t/read-before-installing-sunnypilot/254), as well as a complete list of [Recommended Branch Installations](https://community.sunnypilot.ai/t/recommended-branch-installations/235).

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
