#include <array>

#include "common/tests/native_test.h"
#include "tools/cabana/streams/abstractstream.h"
#include "tools/cabana/dbc/dbcfile.h"

void test_flexray_cycle() {
  DBCFile diagnostics("openpilot/tools/cabana/dbc/examples/fpga_logging_diagnostics.dbc");
  const auto *diagnostic = diagnostics.msg(0x1fa);
  REQUIRE(diagnostic != nullptr);
  REQUIRE(diagnostic->multiplexor->size == 8);
  const std::array<const char *, 8> names = {"SNAPSHOT_BYTES_00_05", "SNAPSHOT_BYTES_06_11", "SNAPSHOT_BYTES_12_17", "SNAPSHOT_BYTES_18_23",
                                          "SNAPSHOT_BYTES_24_29", "SNAPSHOT_BYTES_30_35", "SNAPSHOT_BYTES_36_41", "SNAPSHOT_BYTES_42_47"};
  for (int selector = 0; selector < 256; ++selector) {
    std::array<uint8_t, 8> bytes = {(uint8_t)selector, 255, 0x78, 0x56, 0x34, 0x12, 0xab, 0xcd};
    for (int page = 0; page < 8; ++page) {
      double sequence = -1;
      auto sequence_signal = diagnostic->sig("SNAPSHOT_SEQUENCE_PAGE_" + std::to_string(page));
      REQUIRE(sequence_signal != nullptr);
      REQUIRE(sequence_signal->getValue(bytes.data(), bytes.size(), &sequence) == (selector == 32 + page));
      if (selector == 32 + page) REQUIRE(sequence == 255);
      double value = -1;
      REQUIRE(diagnostic->sig(names[page])->getValue(bytes.data(), bytes.size(), &value) == (selector == 32 + page));
      if (selector == 32 + page) REQUIRE(value == 0xcdab12345678ULL);
    }
    for (const auto *name : {"FIRMWARE_MAJOR", "FIRMWARE_MINOR", "FIRMWARE_PATCH", "FIRMWARE_BUILD_ID"}) {
      double value = -1;
      REQUIRE(diagnostic->sig(name)->getValue(bytes.data(), bytes.size(), &value) == (selector == 0x2f));
      if (selector == 0x2f) {
        const double expected = std::string(name) == "FIRMWARE_MAJOR" ? 255 : std::string(name) == "FIRMWARE_MINOR" ? 0x78 :
                                std::string(name) == "FIRMWARE_PATCH" ? 0x56 : 0xcdab1234;
        REQUIRE(value == expected);
      }
    }
  }

  DBCFile file("openpilot/tools/cabana/dbc/examples/flexray_cycle.dbc");
  auto msg = file.msg(0x0f);
  REQUIRE(msg != nullptr);
  REQUIRE(file.getMessages().size() == 1);
  REQUIRE(msg->multiplexor != nullptr);
  REQUIRE(msg->multiplexor->start_bit == 8);
  auto counter = msg->sig("CYCLE_COUNTER");
  auto even = msg->sig("EVEN_PAYLOAD_BYTE");
  auto odd = msg->sig("ODD_PAYLOAD_BYTE");
  REQUIRE(counter != nullptr);
  REQUIRE(even != nullptr);
  REQUIRE(odd != nullptr);

  std::array<uint8_t, 9> data = {0xff, 0, 0x42};
  for (int cycle = 0; cycle < 64; ++cycle) {
    data[1] = cycle;
    double value = -1;
    REQUIRE(counter->getValue(data.data(), data.size(), &value));
    REQUIRE(value == cycle);
    REQUIRE(even->getValue(data.data(), data.size(), &value) == (cycle % 2 == 0));
    REQUIRE(odd->getValue(data.data(), data.size(), &value) == (cycle % 2 == 1));
    REQUIRE(value == 0x42);
    REQUIRE(msg->address == 0x0f);
  }

  // Any low-bit cycle selector is configured in the viewer, not the capture.
  for (int bits : {2, 3, 4, 6}) {
    msg->multiplexor->size = bits;
    msg->multiplexor->update();
    even->multiplex_value = 0;
    for (int cycle = 0; cycle < 64; ++cycle) {
      data[1] = cycle;
      double value = -1;
      REQUIRE(even->getValue(data.data(), data.size(), &value) == (cycle % (1 << bits) == 0));
    }
  }
}

namespace {
class PayloadTestStream : public AbstractStream {
public:
  PayloadTestStream() : previous_(::can) { ::can = this; }
  ~PayloadTestStream() override { ::can = previous_; }
  void start() override {}
  std::string routeName() const override { return ""; }
  using AbstractStream::mergeEvents;
  using AbstractStream::newEvent;
  using AbstractStream::updateEvent;
  using AbstractStream::updateLastMessages;
private:
  AbstractStream *previous_;
};
}

void test_flexray_stream() {
  PayloadTestStream stream;
  capnp::MallocMessageBuilder message;
  auto frame = message.initRoot<cereal::Event>().initCan(1)[0];
  std::vector<uint8_t> data(259, 0x55);
  data[0] = 3;
  data[1] = 7;
  frame.setSrc(6);
  frame.setAddress(15);
  frame.setDat(kj::arrayPtr(data.data(), data.size()));
  const auto *event = stream.newEvent(100, frame.asReader());
  REQUIRE(event->size == data.size());
  REQUIRE(event->src == 6);
  REQUIRE(event->address == 15);
  REQUIRE(std::equal(data.begin(), data.end(), event->dat));
  REQUIRE(cabana::maxMessageSize(6) == 259);
  REQUIRE(cabana::maxMessageSize(4) == 259);
  frame.setSrc(4);
  const auto *bcm = stream.newEvent(101, frame.asReader());
  REQUIRE(bcm->src == 4 && bcm->address == event->address);
  REQUIRE(std::equal(data.begin(), data.end(), bcm->dat));
  REQUIRE(cabana::maxMessageSize(2) == 64);
  stream.updateEvent({.source = 6, .address = 15}, 1.0, event->dat, event->size);
  stream.updateLastMessages();
  REQUIRE(stream.lastMessage({.source = 6, .address = 15}).dat == data);

  frame.setSrc(2);
  stream.mergeEvents({stream.newEvent(10, frame.asReader()), stream.newEvent(30, frame.asReader())});
  frame.setSrc(6);
  const auto *flexray = stream.newEvent(20, frame.asReader());
  frame.setSrc(2);
  stream.mergeEvents({flexray, stream.newEvent(25, frame.asReader()), stream.newEvent(40, frame.asReader())});
  std::vector<uint64_t> times;
  for (const auto *item : stream.allEvents()) times.push_back(item->mono_time);
  REQUIRE(times == std::vector<uint64_t>({10, 20, 25, 30, 40}));
  times.clear();
  for (const auto *item : stream.events({.source = 2, .address = 15})) times.push_back(item->mono_time);
  REQUIRE(times == std::vector<uint64_t>({10, 25, 30, 40}));
}
