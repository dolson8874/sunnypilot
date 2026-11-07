
#undef INFO
#include <QDir>
#include <QCoreApplication>

#include "catch2/catch.hpp"
#include "tools/cabana/dbc/dbcmanager.h"
#include "tools/cabana/streams/abstractstream.h"

namespace {
class PayloadTestStream : public AbstractStream {
public:
  explicit PayloadTestStream(QObject *parent) : AbstractStream(parent), previous_(::can) { ::can = this; }
  ~PayloadTestStream() override { ::can = previous_; }
  void start() override {}
  std::string routeName() const override { return ""; }
  using AbstractStream::newEvent;
  using AbstractStream::updateEvent;
  using AbstractStream::mergeEvents;
private:
  AbstractStream *previous_;
};
}

TEST_CASE("FlexRay events preserve payloads and use a separate source namespace") {
  QObject parent;
  PayloadTestStream stream(&parent);
  MessageBuilder msg;
  auto frame = msg.initEvent().initCan(1)[0];
  std::vector<uint8_t> data(259, 0x55);
  data[0] = 3;
  data[1] = 7;
  data[256] = 0x12;
  data[257] = 0x34;
  data[258] = 0x56;
  frame.setAddress(15);
  frame.setSrc(6);
  frame.setDat(kj::arrayPtr(data.data(), data.size()));
  const auto *event = stream.newEvent(100, frame.asReader());
  REQUIRE(event->src == 6);
  REQUIRE(event->address == 15);
  REQUIRE(event->size == 259);
  REQUIRE(std::equal(data.begin(), data.end(), event->dat));
  REQUIRE(cabana::isFlexraySource(event->src));
  REQUIRE_FALSE(cabana::isFlexraySource(2));
  REQUIRE_FALSE(cabana::isFlexraySource(12));
}

TEST_CASE("FlexRay CAN events retain cycle multiplexing") {
  DBCFile dbc("tools/cabana/dbc/examples/flexray_cycle.dbc");
  auto *even = dbc.signal(15, "EVEN_PAYLOAD_BYTE");
  auto *odd = dbc.signal(15, "ODD_PAYLOAD_BYTE");
  REQUIRE(even != nullptr);
  REQUIRE(odd != nullptr);
  QObject parent;
  PayloadTestStream stream(&parent);
  MessageBuilder message;
  auto frame = message.initEvent().initCan(1)[0];
  frame.setAddress(15);
  frame.setSrc(6);
  for (int cycle = 0; cycle < 64; ++cycle) {
    std::vector<uint8_t> data = {3, uint8_t(cycle), 0x55, 0, 0, 0, 0x12, 0x34, 0x56};
    frame.setDat(kj::arrayPtr(data.data(), data.size()));
    const auto *event = stream.newEvent(cycle, frame.asReader());
    double value = 0;
    REQUIRE(even->getValue(event->dat, event->size, &value) == (cycle % 2 == 0));
    REQUIRE(odd->getValue(event->dat, event->size, &value) == (cycle % 2 == 1));
    REQUIRE(value == 0x55);
  }
}

TEST_CASE("Overlapping event batches retain chronological order") {
  QObject parent;
  PayloadTestStream stream(&parent);
  MessageBuilder msg;
  auto c = msg.initEvent().initCan(1)[0];
  c.setSrc(2);
  c.setAddress(15);
  stream.mergeEvents({stream.newEvent(10, c.asReader()), stream.newEvent(30, c.asReader())});
  c.setSrc(6);
  const auto *flexray = stream.newEvent(20, c.asReader());
  c.setSrc(2);
  stream.mergeEvents({flexray, stream.newEvent(25, c.asReader()), stream.newEvent(40, c.asReader())});
  std::vector<uint64_t> times;
  for (const auto *event : stream.allEvents()) times.push_back(event->mono_time);
  REQUIRE(times == std::vector<uint64_t>{10, 20, 25, 30, 40});
  times.clear();
  for (const auto *event : stream.events({.source = 2, .address = 15})) times.push_back(event->mono_time);
  REQUIRE(times == std::vector<uint64_t>{10, 25, 30, 40});
}

TEST_CASE("AbstractStream preserves payloads longer than 255 bytes") {
  QObject parent;
  PayloadTestStream stream(&parent);
  for (size_t size : {8, 64, 254, 255, 256, 259, 512}) {
    CAPTURE(size);
    std::vector<uint8_t> payload(size);
    for (size_t i = 0; i < size; ++i) payload[i] = i;
    MessageBuilder msg;
    auto c = msg.initEvent().initCan(1)[0];
    c.setAddress(0x7f00);
    c.setSrc(2);
    c.setDat(kj::arrayPtr(payload.data(), payload.size()));
    const auto *event = stream.newEvent(1000000000, c.asReader());
    REQUIRE(event->size == size);
    REQUIRE(std::equal(payload.begin(), payload.end(), event->dat));
    MessageId id = {.source = event->src, .address = event->address};
    stream.updateEvent(id, 1.0, event->dat, event->size);
    stream.privateUpdateLastMsgsSignal();
    QCoreApplication::processEvents();
    REQUIRE(stream.lastMessage(id).dat == payload);
  }
}

const std::string TEST_RLOG_URL = "https://commadataci.blob.core.windows.net/openpilotci/0c94aa1e1296d7c6/2021-05-05--19-48-37/0/rlog.bz2";

TEST_CASE("DBCFile::generateDBC") {
  std::string fn = std::string(OPENDBC_FILE_PATH) + "/tesla_can.dbc";
  DBCFile dbc_origin(fn);
  DBCFile dbc_from_generated("", dbc_origin.generateDBC());

  REQUIRE(dbc_origin.getMessages().size() == dbc_from_generated.getMessages().size());
  auto &msgs = dbc_origin.getMessages();
  auto &new_msgs = dbc_from_generated.getMessages();
  for (auto &[id, m] : msgs) {
    auto &new_m = new_msgs.at(id);
    REQUIRE(m.name == new_m.name);
    REQUIRE(m.size == new_m.size);
    REQUIRE(m.getSignals().size() == new_m.getSignals().size());
    auto sigs = m.getSignals();
    auto new_sigs = new_m.getSignals();
    for (int i = 0; i < sigs.size(); ++i) {
      REQUIRE(*sigs[i] == *new_sigs[i]);
    }
  }
}

TEST_CASE("DBCFile::generateDBC - comment order") {
  // Ensure that message comments are followed by signal comments and in the correct order
  std::string content = R"(BO_ 160 message_1: 8 EON
 SG_ signal_1 : 0|12@1+ (1,0) [0|4095] "unit" XXX

BO_ 162 message_2: 8 EON
 SG_ signal_2 : 0|12@1+ (1,0) [0|4095] "unit" XXX

CM_ BO_ 160 "message comment";
CM_ SG_ 160 signal_1 "signal comment";
CM_ BO_ 162 "message comment";
CM_ SG_ 162 signal_2 "signal comment";
)";
  DBCFile dbc("", content);
  REQUIRE(dbc.generateDBC() == content);
}

TEST_CASE("DBCFile::generateDBC -- preserve original header") {
  std::string content = R"(VERSION "1.0"

NS_ :
 CM_

BS_:

BU_: EON

BO_ 160 message_1: 8 EON
 SG_ signal_1 : 0|12@1+ (1,0) [0|4095] "unit" XXX

CM_ BO_ 160 "message comment";
CM_ SG_ 160 signal_1 "signal comment";
)";
  DBCFile dbc("", content);
  REQUIRE(dbc.generateDBC() == content);
}

TEST_CASE("DBCFile::generateDBC - escaped quotes") {
  std::string content = R"(BO_ 160 message_1: 8 EON
 SG_ signal_1 : 0|12@1+ (1,0) [0|4095] "unit" XXX

CM_ BO_ 160 "message comment with \"escaped quotes\"";
CM_ SG_ 160 signal_1 "signal comment with \"escaped quotes\"";
)";
  DBCFile dbc("", content);
  REQUIRE(dbc.generateDBC() == content);
}

TEST_CASE("parse_dbc") {
  std::string content = R"(
BO_ 160 message_1: 8 EON
  SG_ signal_1 : 0|12@1+ (1,0) [0|4095] "unit"  XXX
  SG_ signal_2 : 12|1@1+ (1.0,0.0) [0.0|1] ""  XXX

BO_ 162 message_1: 8 XXX
  SG_ signal_1 M : 0|12@1+ (1,0) [0|4095] "unit" XXX
  SG_ signal_2 M4 : 12|1@1+ (1.0,0.0) [0.0|1] "" XXX

VAL_ 160 signal_1 0 "disabled" 1.2 "initializing" 2 "fault";

CM_ BO_ 160 "message comment" ;
CM_ SG_ 160 signal_1 "signal comment";
CM_ SG_ 160 signal_2 "multiple line comment 
1
2
";

CM_ BO_ 162 "message comment with \"escaped quotes\"";
CM_ SG_ 162 signal_1 "signal comment with \"escaped quotes\"";
)";

  DBCFile file("", content);
  auto msg = file.msg(160);
  REQUIRE(msg != nullptr);
  REQUIRE(msg->name == "message_1");
  REQUIRE(msg->size == 8);
  REQUIRE(msg->comment == "message comment");
  REQUIRE(msg->sigs.size() == 2);
  REQUIRE(msg->transmitter == "EON");
  REQUIRE(file.msg("message_1") != nullptr);

  auto sig_1 = msg->sigs[0];
  REQUIRE(sig_1->name == "signal_1");
  REQUIRE(sig_1->start_bit == 0);
  REQUIRE(sig_1->size == 12);
  REQUIRE(sig_1->min == 0);
  REQUIRE(sig_1->max == 4095);
  REQUIRE(sig_1->unit == "unit");
  REQUIRE(sig_1->comment == "signal comment");
  REQUIRE(sig_1->receiver_name == "XXX");
  REQUIRE(sig_1->val_desc.size() == 3);
  REQUIRE(sig_1->val_desc[0] == std::pair<double, std::string>{0, "disabled"});
  REQUIRE(sig_1->val_desc[1] == std::pair<double, std::string>{1.2, "initializing"});
  REQUIRE(sig_1->val_desc[2] == std::pair<double, std::string>{2, "fault"});

  auto &sig_2 = msg->sigs[1];
  REQUIRE(sig_2->comment == "multiple line comment \n1\n2");

  // multiplexed signals
  msg = file.msg(162);
  REQUIRE(msg != nullptr);
  REQUIRE(msg->sigs.size() == 2);
  REQUIRE(msg->sigs[0]->type == cabana::Signal::Type::Multiplexor);
  REQUIRE(msg->sigs[1]->type == cabana::Signal::Type::Multiplexed);
  REQUIRE(msg->sigs[1]->multiplex_value == 4);
  REQUIRE(msg->sigs[1]->start_bit == 12);
  REQUIRE(msg->sigs[1]->size == 1);
  REQUIRE(msg->sigs[1]->receiver_name == "XXX");

  // escaped quotes
  REQUIRE(msg->comment == "message comment with \"escaped quotes\"");
  REQUIRE(msg->sigs[0]->comment == "signal comment with \"escaped quotes\"");
}

TEST_CASE("parse_opendbc") {
  QDir dir(OPENDBC_FILE_PATH);
  QStringList errors;
  for (auto fn : dir.entryList({"*.dbc"}, QDir::Files, QDir::Name)) {
    try {
      auto dbc = DBCFile(dir.filePath(fn).toStdString());
    } catch (std::exception &e) {
      errors.push_back(e.what());
    }
  }
  INFO(errors.join("\n").toStdString());
  REQUIRE(errors.empty());
}
