
#include "selfdrive/pandad/panda.h"  // for  _USE_FLEXRAY_HARNESS_

#ifdef _USE_FLEXRAY_HARNESS_

#include <sys/file.h>
#include <sys/ioctl.h>

#include <cassert>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <sstream>

#include "common/util.h"
#include "common/timing.h"
#include "common/swaglog.h"
#include "panda/board/comms_definitions.h"
#include "selfdrive/pandad/panda_comms.h"

#define FTDI_DEVICE_ID  0x0403
#if 0
#define FTDI_PRODUCT_ID 0x6010
#else
#define FTDI_PRODUCT_ID 0x6011
#endif

#define PREFIX_SN "FLX"

#define FLEXRAY_SOCKET_PATH   "/tmp/flexraylogd_unix_socket"

int connect_to_server(struct sockaddr_un *addr) {
    int sfd;

    sfd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (sfd < 0) {
        perror("ftdi: fail create socket");
        return -1;
    }
    if (connect(sfd, (struct sockaddr*)addr, sizeof(struct sockaddr_un)) < 0) {
        perror("ftdi : fail connecting flexray_logd");
        close(sfd);
        return -1;
    }
    return sfd;
}

PandaFtdiHandle::PandaFtdiHandle(std::string serial) : PandaCommsHandle(serial) {
  char serial_no[128];

  sprintf(serial_no, "%s%04x%04x", PREFIX_SN, FTDI_DEVICE_ID, FTDI_PRODUCT_ID);

  hw_serial =  serial_no;
  sockfd = -1;

  memset(&sock_addr, 0, sizeof(sock_addr));
  sock_addr.sun_family = AF_UNIX;
  strncpy(sock_addr.sun_path, FLEXRAY_SOCKET_PATH, sizeof(sock_addr.sun_path) - 1);

  return;
}


PandaFtdiHandle::~PandaFtdiHandle() {
  std::lock_guard lk(hw_lock);
  cleanup();
  connected = false;
}

void PandaFtdiHandle::cleanup() {
  if(sockfd < 0) close (sockfd);
}



int PandaFtdiHandle::control_write(uint8_t request, uint16_t param1, uint16_t param2, unsigned int timeout) {

  return 0;
}

int PandaFtdiHandle::control_read(uint8_t request, uint16_t param1, uint16_t param2, unsigned char *data, uint16_t length, unsigned int timeout) {

  switch(request) {
    case 0xc1 :
      *data = ((int)cereal::PandaState::PandaType::FLEXRAY_PANDA);
      break;

    // state health
    case 0xd2 :
    #if 0
      {
      struct health_t *ph = (struct health_t *) data;
      ph->ignition_line_pkt =  true;
      ph->ignition_can_pkt = true;
      }
    #endif

      break;

    // can health
    case 0xc2 :
      break;

    // firmware
    case 0xd3 :
      break;
    case 0xd4:
      break;

    default:
      break;
  }

  return 0;
}

int PandaFtdiHandle::bulk_write(unsigned char endpoint, unsigned char* data, int length, unsigned int timeout) {

  return 0;
}

int PandaFtdiHandle::bulk_read(unsigned char endpoint, unsigned char* data, int length, unsigned int timeout) {
  int recv = -1;
  struct timeval tv;

  tv.tv_sec = 0;
  tv.tv_usec = timeout;


  sockfd = connect_to_server(&sock_addr);

  if(sockfd >= 0) {
    char cmd_buf[3];

    cmd_buf[0] = 0x80;
    cmd_buf[1] = (length & 0xff00) >> 8;
    cmd_buf[2] = (length & 0xff) ;

    setsockopt(sockfd, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));

    write(sockfd, cmd_buf, 3);
    recv = read(sockfd, data, length);
  }

  if(recv < 0)
  {
    LOGW("FTDI : fail read_data %d", recv);
    comms_healthy = false;
  }

  close(sockfd);
  sockfd = -1;

  return recv;
}


std::vector<std::string> PandaFtdiHandle::list() {
  std::vector<std::string> serials;

  int sfd;
  char serial_no[128];
  char data[RECV_SIZE];

  struct sockaddr_un saddr;


  memset(&saddr, 0, sizeof(saddr));
  saddr.sun_family = AF_UNIX;
  strncpy(saddr.sun_path, FLEXRAY_SOCKET_PATH, sizeof(saddr.sun_path) - 1);

  sfd = connect_to_server(&saddr);

  if(sfd >= 0) {
    char cmd_buf[3];

    cmd_buf[0] = 0x1F;  // reset buffer

    write(sfd, cmd_buf, 1);
    read(sfd, data, 2);
    sprintf(serial_no, "%s%04x%04x", PREFIX_SN, FTDI_DEVICE_ID, FTDI_PRODUCT_ID);
    serials.push_back(serial_no);
    close(sfd);
  }

  return serials;
}


#endif
