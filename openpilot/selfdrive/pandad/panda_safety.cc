#include "selfdrive/pandad/pandad.h"
#include "openpilot/cereal/messaging/messaging.h"
#include "common/swaglog.h"

void PandaSafety::configureSafetyMode(bool is_onroad) {
  if (is_onroad && !safety_configured_) {
    if (!updateMultiplexingMode()) {
      return;
    }

    auto car_params = fetchCarParams();
    if (!car_params.empty()) {
      LOGW("got %lu bytes CarParams", car_params[0].size());
      LOGW("got %lu bytes CarParamsSP", car_params[1].size());
      setSafetyMode(car_params);
      safety_configured_ = true;
    }
  } else if (!is_onroad) {
    initialized_ = false;
    safety_configured_ = false;
    log_once_ = false;
  }
}

bool PandaSafety::updateMultiplexingMode() {
  const bool requested = params_.getBool("ObdMultiplexingEnabled");
  const std::string applied = params_.get("ObdMultiplexingApplied");
  if (!initialized_ || requested != prev_obd_multiplexing_ || applied != (requested ? "1" : "0")) {
    if (!initialized_) {
      params_.remove("ObdMultiplexingApplied");
    }

    // Publish the actual mode even if this Panda connected while OFF was already requested.
    const uint16_t safety_param = requested ? 0U : 1U;
    if (!panda_->set_safety_model(cereal::CarParams::SafetyModel::ELM327, safety_param) ||
        params_.putBool("ObdMultiplexingApplied", requested) != 0) {
      return false;
    }
    prev_obd_multiplexing_ = requested;
    initialized_ = true;
  }
  return true;
}

// TODO-SP: Use structs instead of vector
std::vector<std::string> PandaSafety::fetchCarParams() {
  if (!params_.getBool("FirmwareQueryDone")) {
    return {};
  }

  if (!log_once_) {
    LOGW("Finished FW query, Waiting for params to set safety model");
    log_once_ = true;
  }

  if (!params_.getBool("ControlsReady")) {
    return {};
  }
  return {params_.get("CarParams"), params_.get("CarParamsSP")};
}

std::pair<cereal::CarParams::SafetyModel, uint16_t> PandaSafety::getSafetyConfig(cereal::CarParams::Reader car_params) {
  const auto configs = car_params.getSafetyConfigs();
  if (configs.size() == 0) {
    return {cereal::CarParams::SafetyModel::NO_OUTPUT, 0U};
  }
  const auto model = configs[0].getSafetyModel();
  // ID 35 was Land Rover in the old fork; upstream now assigns it to BYD.
  if (car_params.getBrand() == "landrover" && model == cereal::CarParams::SafetyModel::BYD) {
    LOGE("Refusing legacy Land Rover safety ID 35; regenerate CarParams with the matching firmware");
    return {cereal::CarParams::SafetyModel::NO_OUTPUT, 0U};
  }
  return {model, configs[0].getSafetyParam()};
}

// TODO-SP: Use structs instead of vector
void PandaSafety::setSafetyMode(const std::vector<std::string> &params_string) {
  AlignedBuffer aligned_buf;
  AlignedBuffer aligned_buf_sp;

  capnp::FlatArrayMessageReader cmsg(aligned_buf.align(params_string[0].data(), params_string[0].size()));
  cereal::CarParams::Reader car_params = cmsg.getRoot<cereal::CarParams>();

  capnp::FlatArrayMessageReader cmsg_sp(aligned_buf_sp.align(params_string[1].data(), params_string[1].size()));
  cereal::CarParamsSP::Reader car_params_sp = cmsg_sp.getRoot<cereal::CarParamsSP>();

  uint16_t alternative_experience = car_params.getAlternativeExperience();
  uint16_t safety_param_sp = car_params_sp.getSafetyParam();

  auto [safety_model, safety_param] = getSafetyConfig(car_params);

  LOGW("setting safety model: %d, param: %d, alternative experience: %d, param_sp: %d", (int)safety_model, safety_param, alternative_experience, safety_param_sp);
  panda_->set_alternative_experience(alternative_experience, safety_param_sp);
  panda_->set_safety_model(safety_model, safety_param);
}

bool PandaSafety::getOffroadMode() {
  auto offroad_mode = params_.getBool("OffroadMode");
  return offroad_mode;
}
