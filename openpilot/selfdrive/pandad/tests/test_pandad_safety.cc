#include <capnp/message.h>
#include <cstdlib>
#include <filesystem>
#include <tuple>

#include "common/tests/native_test.h"
#include "selfdrive/pandad/pandad.h"

void test_safety_config() {
  using Model = cereal::CarParams::SafetyModel;
  CHECK(static_cast<int>(Model::BYD) == 35);
  CHECK(static_cast<int>(Model::LANDROVER) == 39);

  capnp::MallocMessageBuilder message;
  auto params = message.initRoot<cereal::CarParams>();
  params.setBrand("landrover");
  auto config = params.initSafetyConfigs(1)[0];
  config.setSafetyParam(1);
  config.setSafetyModel(Model::BYD);
  auto [model, param] = PandaSafety::getSafetyConfig(params.asReader());
  CHECK(model == Model::NO_OUTPUT);
  CHECK(param == 0);

  config.setSafetyModel(Model::LANDROVER);
  std::tie(model, param) = PandaSafety::getSafetyConfig(params.asReader());
  CHECK(model == Model::LANDROVER);
  CHECK(param == 1);

  params.setBrand("byd");
  config.setSafetyModel(Model::BYD);
  std::tie(model, param) = PandaSafety::getSafetyConfig(params.asReader());
  CHECK(model == Model::BYD);
  CHECK(param == 1);

  params.setBrand("landrover");
  config.setSafetyModel(Model::NO_OUTPUT);
  std::tie(model, param) = PandaSafety::getSafetyConfig(params.asReader());
  CHECK(model == Model::NO_OUTPUT);

  params.initSafetyConfigs(0);
  std::tie(model, param) = PandaSafety::getSafetyConfig(params.asReader());
  CHECK(model == Model::NO_OUTPUT);
  CHECK(param == 0);
}

namespace {

bool safety_write_succeeds = true;
std::vector<uint16_t> obd_writes;

}  // namespace

// Link PandaSafety to a Panda double so the test exercises real Params without a USB device.
Panda::Panda(std::string) {}

bool Panda::set_safety_model(cereal::CarParams::SafetyModel model, uint16_t param) {
  CHECK(model == cereal::CarParams::SafetyModel::ELM327);
  obd_writes.push_back(param);
  return safety_write_succeeds;
}

void Panda::set_alternative_experience(uint16_t, uint16_t) {
  CHECK(false);
}

void test_obd_multiplexing() {
  char path[] = "/tmp/pandad-obd-test-XXXXXX";
  CHECK(mkdtemp(path) != nullptr);
  CHECK(setenv("PARAMS_ROOT", path, 1) == 0);
  {
    Params params;
    Panda panda("test");
    PandaSafety initial(&panda);
    initial.configureSafetyMode(true);
    CHECK(params.get("ObdMultiplexingApplied") == "0");
    CHECK(obd_writes == std::vector<uint16_t>{1});

    CHECK(params.putBool("ObdMultiplexingEnabled", true) == 0);
    initial.configureSafetyMode(true);
    CHECK(params.get("ObdMultiplexingApplied") == "1");
    CHECK(obd_writes.back() == 0);

    CHECK(params.putBool("ObdMultiplexingEnabled", false) == 0);
    PandaSafety reconnected(&panda);
    safety_write_succeeds = false;
    reconnected.configureSafetyMode(true);
    CHECK(params.get("ObdMultiplexingApplied").empty());
    CHECK(obd_writes.back() == 1);

    safety_write_succeeds = true;
    reconnected.configureSafetyMode(true);
    CHECK(params.get("ObdMultiplexingApplied") == "0");
    CHECK(obd_writes.back() == 1);

    CHECK(params.remove("ObdMultiplexingApplied") == 0);
    reconnected.configureSafetyMode(true);
    CHECK(params.get("ObdMultiplexingApplied") == "0");

    CHECK(params.putBool("ObdMultiplexingEnabled", true) == 0);
    PandaSafety reconnected_with_obd_on(&panda);
    reconnected_with_obd_on.configureSafetyMode(true);
    CHECK(params.get("ObdMultiplexingApplied") == "1");
    CHECK(obd_writes.back() == 0);
  }
  std::filesystem::remove_all(path);
}

int main() {
  return run_native_test([] { test_safety_config(); test_obd_multiplexing(); });
}
