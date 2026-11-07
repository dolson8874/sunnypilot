# Cabana

Cabana is a tool developed to view raw CAN data. One use for this is creating and editing [CAN Dictionaries](http://socialledge.com/sjsu/index.php/DBC_Format) (DBC files), and the tool provides direct integration with [commaai/opendbc](https://github.com/commaai/opendbc) (a collection of DBC files), allowing you to load the DBC files direct from source, and save to your fork. In addition, you can load routes from [comma connect](https://connect.comma.ai).

## Usage Instructions

```bash
$ ./cabana -h
Usage: ./cabana [options] route

Options:
  -h, --help                     Displays help on commandline options.
  --help-all                     Displays help including Qt specific options.
  --demo                         use a demo route instead of providing your own
  --auto                         Auto load the route from the best available source (no video):
                                 internal, openpilotci, comma_api, car_segments, testing_closet
  --qcam                         load qcamera
  --ecam                         load wide road camera
  --msgq                         read can messages from msgq
  --panda                        read can messages from panda
  --panda-serial <panda-serial>  read can messages from panda with given serial
  --socketcan <socketcan>        read can messages from given SocketCAN device
  --zmq <ip-address>             read can messages from zmq at the specified ip-address
                                 messages
  --data_dir <data_dir>          local directory with routes
  --no-vipc                      do not output video
  --dbc <dbc>                    dbc file to open

Arguments:
  route                          the drive to replay. find your drives at
                                 connect.comma.ai
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
cabana "5beb9b58bd12b691/0000010a--a51155e496" --dcam --ecam
```

### Streaming CAN Messages from a comma Device

[SSH into your device](https://github.com/commaai/openpilot/wiki/SSH) and start the bridge with the following command:

```shell
cd /data/openpilot/cereal/messaging/
./bridge &
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

`system/flexray_logd` retains its old ID/counter classification code but does not execute it.
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
