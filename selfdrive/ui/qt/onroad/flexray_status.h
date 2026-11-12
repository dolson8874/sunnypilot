#pragma once

#include <QCoreApplication>
#include <QPainter>
#include <QWidget>

#include "common/params.h"
#include "common/timing.h"
#include "cereal/messaging/messaging.h"

// Display-only subscriber. Alerts are layered above this widget.
class FlexrayStatusWidget : public QWidget {
public:
  explicit FlexrayStatusWidget(QWidget *parent = nullptr) : QWidget(parent), sm({"flexrayStatus"}) {
    setAttribute(Qt::WA_TransparentForMouseEvents);
  }

  void refresh(bool started, int dev_info, bool alert_visible) {
    sm.update(0);
    const uint64_t now = nanos_since_boot();
    if (now - param_time >= 1000000000ULL || param_time == 0) {
      show_status = params.getBool("FlexrayShowStatus");
      logging_enabled = params.getBool("FlexrayLoggingEnabled");
      param_time = now;
    }
    draw_status = started && show_status && !alert_visible;
    bottom_debug = dev_info == 2;
    right_debug = dev_info != 0;
    update();
  }

protected:
  void paintEvent(QPaintEvent *) override {
    if (!draw_status) return;
    const auto status = sm["flexrayStatus"].getFlexrayStatus();
    const uint64_t now = nanos_since_boot();
    // Python activity timestamps use CLOCK_MONOTONIC; socket receipt uses boot time.
    // Keep the domains separate so suspend time cannot make valid data look stale.
    struct timespec activity_time;
    clock_gettime(CLOCK_MONOTONIC, &activity_time);
    const uint64_t activity_now = activity_time.tv_sec * 1000000000ULL + activity_time.tv_nsec;
    const uint64_t received = sm.rcv_time("flexrayStatus");
    const bool fresh = received && now >= received && now - received < 3000000000ULL;
    const auto state = QString::fromUtf8(status.getState().cStr());
    QString label = text("Waiting for data");
    QString detail;
    QColor color(255, 190, 70);
    if (!logging_enabled) {
      label = text("Recording disabled");
      color = QColor(180, 180, 180);
    } else if (!fresh) {
      label = text("Status unavailable");
    } else if (state == "retrying") {
      label = text("Retrying capture");
      detail = text("Retries: %1").arg(status.getRetryCount());
    } else if (state == "stopped") {
      label = text("Capture stopped");
    } else if (state == "buffering") {
      label = text("Preparing recording");
      detail = text("Buffered: %1 frames").arg(status.getStartupBufferedFrames());
    } else if (status.getLastFrameMonoTime() > 0 && activity_now >= status.getLastFrameMonoTime() &&
               activity_now - status.getLastFrameMonoTime() < 2000000000ULL) {
      label = text("Receiving");
      detail = QString("4: %1/s   6: %2/s").arg(status.getSrc4Rate(), 0, 'f', 0).arg(status.getSrc6Rate(), 0, 'f', 0);
      color = QColor(90, 230, 140);
    } else if (state == "starting") {
      label = text("Starting capture");
    }
    // Reserve the driver icon, bottom debug bar and right debug column.
    const int card_width = std::min(440, width() - 48 - (right_debug ? 224 : 0));
    if (card_width < 160 || height() < 380) return;
    const QRect card(24, height() - 222 - (bottom_debug ? 61 : 0) - 124, card_width, 112);
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.setPen(Qt::NoPen);
    painter.setBrush(QColor(0, 0, 0, 170));
    painter.drawRoundedRect(card, 16, 16);
    QFont font = painter.font();
    font.setPixelSize(30);
    painter.setFont(font);
    painter.setPen(color);
    const QRect title = card.adjusted(16, 10, -16, -55);
    painter.drawText(title, Qt::AlignVCenter, painter.fontMetrics().elidedText("FlexRay: " + label, Qt::ElideRight, title.width()));
    font.setPixelSize(27);
    painter.setFont(font);
    painter.setPen(Qt::white);
    const QRect body = card.adjusted(16, 57, -16, -10);
    painter.drawText(body, Qt::AlignVCenter, painter.fontMetrics().elidedText(detail, Qt::ElideRight, body.width()));
  }

private:
  static QString text(const char *source) { return QCoreApplication::translate("FlexrayStatusWidget", source); }
  SubMaster sm;
  Params params;
  uint64_t param_time = 0;
  bool show_status = false, logging_enabled = false, draw_status = false;
  bool bottom_debug = false, right_debug = false;
};
