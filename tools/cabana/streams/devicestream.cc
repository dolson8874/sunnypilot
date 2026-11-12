#include "tools/cabana/streams/devicestream.h"

#include <memory>
#include <string>

#include <QButtonGroup>
#include <QFormLayout>
#include <QRadioButton>
#include <QRegularExpression>
#include <QRegularExpressionValidator>
#include <QThread>

// DeviceStream

DeviceStream::DeviceStream(QObject *parent, QString address) : zmq_address(address), LiveStream(parent) {
}

void DeviceStream::streamThread() {
  zmq_address.isEmpty() ? unsetenv("ZMQ") : setenv("ZMQ", "1", 1);

  std::unique_ptr<Context> context(Context::create());
  std::string address = zmq_address.isEmpty() ? "127.0.0.1" : zmq_address.toStdString();
  std::unique_ptr<SubSocket> can_sock(SubSocket::create(context.get(), "can", address));
  std::unique_ptr<SubSocket> flexray_sock(SubSocket::create(context.get(), "flexray", address));
  assert(can_sock && flexray_sock);
  std::unique_ptr<Poller> poller(Poller::create());
  poller->registerSocket(can_sock.get());
  poller->registerSocket(flexray_sock.get());
  while (!QThread::currentThread()->isInterruptionRequested()) {
    for (auto *sock : poller->poll(50)) {
      for (int i = 0; i < 200; ++i) {
        std::unique_ptr<Message> msg(sock->receive(true));
        if (!msg) break;
        handleEvent(kj::ArrayPtr<capnp::word>((capnp::word*)msg->getData(), msg->getSize() / sizeof(capnp::word)));
      }
    }
  }
}

// OpenDeviceWidget

OpenDeviceWidget::OpenDeviceWidget(QWidget *parent) : AbstractOpenStreamWidget(parent) {
  QRadioButton *msgq = new QRadioButton(tr("MSGQ"));
  QRadioButton *zmq = new QRadioButton(tr("ZMQ"));
  ip_address = new QLineEdit(this);
  ip_address->setPlaceholderText(tr("Enter device Ip Address"));
  QString ip_range = "(?:[0-1]?[0-9]?[0-9]|2[0-4][0-9]|25[0-5])";
  QString pattern("^" + ip_range + "\\." + ip_range + "\\." + ip_range + "\\." + ip_range + "$");
  QRegularExpression re(pattern);
  ip_address->setValidator(new QRegularExpressionValidator(re, this));

  group = new QButtonGroup(this);
  group->addButton(msgq, 0);
  group->addButton(zmq, 1);

  QFormLayout *form_layout = new QFormLayout(this);
  form_layout->addRow(msgq);
  form_layout->addRow(zmq, ip_address);
  QObject::connect(group, qOverload<QAbstractButton *, bool>(&QButtonGroup::buttonToggled), [=](QAbstractButton *button, bool checked) {
    ip_address->setEnabled(button == zmq && checked);
  });
  zmq->setChecked(true);
}

AbstractStream *OpenDeviceWidget::open() {
  QString ip = ip_address->text().isEmpty() ? "127.0.0.1" : ip_address->text();
  bool msgq = group->checkedId() == 0;
  return new DeviceStream(qApp, msgq ? "" : ip);
}
