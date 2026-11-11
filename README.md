# 🔐 Safety & Legal Disclaimer
 This repository is for research and development only.
 Use in live vehicles must comply with local laws and safety standards.
 Any damage or consequences are at the user’s responsibility.

<br><br>
# 🚘 This repository adds LAND ROVER vehicles to sunnypilot.

This README describes **`lrmaster-SP`**, the Land Rover upstream-master integration for C3X and C4.
The pinned upstream master is **`3d8f211d4b2d7c4a981633783232c8ff8dbe402b`**
(sunnypilot **2026.003.000**, openpilot **0.11.3**).
`lrmaster-SP-tici` is the separate C3 branch.

| Published branch | Purpose |
| --- | --- |
| `lrmaster-SP` | Land Rover upstream-master integration for C3X and C4; clone command below |
| `lrmaster-SP-tici` | Land Rover branch for C3 |
| `lrmaster-SP-flexraylog` | Legacy FlexRay implementation integrated with pandad |
| `lrmaster-SP-flexraylog-v2` | Standalone FlexRay capture for C3X and C4 |

### Clone this branch

Back up any existing `/data/openpilot` installation before cloning into that path.

```bash
cd /data
git clone --recurse-submodules --branch lrmaster-SP https://github.com/dolson8874/sunnypilot.git openpilot
cd /data/openpilot
scons -j8
```

This base branch does not contain the FlexRay collector. For FlexRay v2 testing, select
`lrmaster-SP-flexraylog-v2` and follow the README on that branch.

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
