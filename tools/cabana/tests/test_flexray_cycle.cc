#undef INFO
#include <array>

#include "catch2/catch.hpp"
#include "tools/cabana/dbc/dbcfile.h"

TEST_CASE("FlexRay example classifies cycles without changing the frame ID") {
  DBCFile file("tools/cabana/dbc/examples/flexray_cycle.dbc");
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
    CAPTURE(cycle);
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
