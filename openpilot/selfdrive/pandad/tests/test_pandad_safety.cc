#include <capnp/message.h>
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

int main() {
  return run_native_test(test_safety_config);
}
