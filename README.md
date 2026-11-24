# 🔐 Safety & Legal Disclaimer
 This repository is for research and development only.
 Use in live vehicles must comply with local laws and safety standards.
 Any damage or consequences are at the user’s responsibility.

<br><br>
# 🚘 This repository adds LAND ROVER vehicles to sunnypilot.

This README describes **`test/lrmaster-SP-tici-wip`**, the C3 test branch based on `test/lrmaster-SP-wip`.

The C3 uses **StarPilot AGNOS 20.5.5** as its operating system. The application, UI, model manager, and vehicle integration come from **sunnypilot `test/lrmaster-SP-wip`**. This port also brings StarPilot’s AR0231 camera support into sunnypilot’s camera service.

### First install on comma three

Keep the device powered with the vehicle cable disconnected while preparing the app and checking the first boot.

#### 1. Install or update StarPilot AGNOS

Follow the [StarPilot installation and update instructions for comma three](https://wiki.firestar.link/software/starpilot/) to prepare the operating system. After the OS reboots, connect over SSH and check:

```sh
cat /VERSION
```

Continue when the output is `20.5.5`. This branch expects that exact C3 version. Check the selected StarPilot release if the output differs. The sunnypilot launcher verifies the device model and OS version before starting the app.

#### 2. Download and activate sunnypilot

Clone to a separate directory and verify the checkout before moving the active app:

```sh
git clone --recurse-submodules --branch test/lrmaster-SP-tici-wip \
  https://github.com/dolson8874/sunnypilot.git /data/openpilot-tici-wip &&
cd /data/openpilot-tici-wip &&
python3 openpilot/common/hardware/comma/starpilot_agnos.py &&
git submodule status --recursive
```

The submodule status lines should begin with a space, indicating the recorded commits are checked out. Before installing the new checkout at `/data/openpilot`, back up the current app path and startup script:

```sh
(
  set -e
  cd /data
  test -x openpilot-tici-wip/launch_openpilot.sh
  backup=$(mktemp -d /data/sunnypilot-backup.XXXXXX)
  if [ -e continue.sh ] || [ -L continue.sh ]; then
    cp -a -- continue.sh "$backup/continue.sh"
  fi
  if [ -e openpilot ] || [ -L openpilot ]; then
    mv -T -- openpilot "$backup/openpilot"
  fi
  if ! mv -T -- openpilot-tici-wip openpilot; then
    if [ -e "$backup/openpilot" ] || [ -L "$backup/openpilot" ]; then
      mv -T -- "$backup/openpilot" openpilot
    fi
    exit 1
  fi
  printf 'Previous app and startup script backup: %s\n' "$backup"
)
```

Keep the printed backup path. The active app now lives at `/data/openpilot`.

#### 3. Check the boot script and first start

AGNOS runs `/data/continue.sh`. A standard script should contain:

```bash
#!/usr/bin/env bash
set -e
cd /data/openpilot
exec ./launch_openpilot.sh
```

If an existing script already starts the app this way, keep it. If the standard script is missing or points to another directory, save the example as `/data/continue.sh` and run `chmod +x /data/continue.sh`. If your device uses custom A/B slot conditions or test settings, preserve those and change only the applicable app working directory to `/data/openpilot`. An old path in this script can leave the device on the StarPilot splash screen.

Run `bash -n /data/continue.sh`, then reboot while the vehicle cable is disconnected. The launcher builds the checkout when there is no `prebuilt` marker. Wait for the sunnypilot UI to open. If it stays on the splash, connect over SSH and check the app path, the startup script, and the startup log with `tmux capture-pane -p -t comma -S -100` or `journalctl -u comma.service -b --no-pager`.

On C3, pandad selects the internal DOS USB port and checks the matching firmware signature and protocol. The first bench launch may update the internal Panda firmware. Retain a known-compatible Panda image for rollback as well as the previous app backup.

### Update an existing C3 checkout

From the already active checkout:

```sh
cd /data/openpilot &&
test "$(git branch --show-current)" = "test/lrmaster-SP-tici-wip" &&
git pull --ff-only &&
git submodule sync --recursive &&
git submodule update --init --recursive &&
git submodule status --recursive
```

If the branch check fails, use the first-install procedure to prepare a separate checkout. A source update on the same active path keeps the boot script in place. For a manual update that changes native code or message schemas, remove the `prebuilt` marker after the update succeeds and reboot while offroad to run the normal build. To build the Panda and pandad targets explicitly, run:

```sh
scons -u -j2 openpilot/selfdrive/pandad/pandad \
  panda/board/obj/panda.bin.signed panda/board/obj/bootstub.panda.bin
```

The software updater stages this branch's app updates in `/data/safe_staging_starpilot`. An update that changes the AGNOS retention policy requires a separately verified checkout. The operating system and boot slots are managed through the StarPilot OS installation tools.

### CAN logging and branch integration

This branch records physical CAN through pandad and loggerd. Enable **Record cruise analysis summaries** in Developer settings to collect optional CAN and radar summaries. The Defender uses Classic CAN on the Panda, including the FPGA link at CAN1 800 kbps. Use the compatible FPGA and harness configuration. Use `test/lrmaster-SP-flexraylog-v2-wip` for USB/SPI FlexRay capture and live FlexRay analysis in Cabana.

`git submodule update --init --recursive` checks out the exact submodule commits recorded by this branch.
Do not use `git submodule update --remote` to prepare a matching device checkout.
When integrating an upstream release, merge and publish the forked `panda` and `opendbc_repo`
commits first, then record their new pointers here. The commits must be reachable from the URLs in `.gitmodules`.
This branch integrates upstream master directly; it does not merge the release stabilization history first.
Source packages now live under `openpilot/`; use the repository root for SCons and dependency setup.
The base WIP defaults to AGNOS 19.9. This test branch requires StarPilot C3 AGNOS 20.5.5 and awaits device and vehicle validation.

Land Rover uses safety model **39** because upstream uses **35 for BYD**, **36 for Volvo**,
**37 for BMW**, and **38 for MG**. Upgrade the application and Panda firmware together.
Regenerate CarParams using the normal startup/fingerprinting process; do not reuse legacy Land Rover safety ID 35.
Pandad rejects a legacy Land Rover configuration that would otherwise select BYD safety.

The pinned `opendbc_repo` retains the Defender WIP implementation and adds Range Rover Vogue 2017. Select **Land Rover Range Rover Vogue 2017** in Vehicle settings if automatic detection is unavailable. The Range Rover uses stock ACC and supports a vehicle-specific MADS toggle. Setting the following distance to 4 disengages steering. The Range Rover port is for offroad verification and has pending vehicle validation.
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
Use [First install on comma three](#first-install-on-comma-three) or [Update an existing C3 checkout](#update-an-existing-c3-checkout) for this WIP. For general sunnypilot setup, see [installation instructions](https://community.sunnypilot.ai/t/read-before-installing-sunnypilot/254), as well as a complete list of [Recommended Branch Installations](https://community.sunnypilot.ai/t/recommended-branch-installations/235).

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
