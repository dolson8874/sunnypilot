#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <stdint.h>
#include "flexray_unpack.h"

#define SOCKET_PATH   "/tmp/flexraylogd_unix_socket"
#define READ_BUF_SIZE (0x4000U)

int connect_to_server() {
    int sockfd;
    struct sockaddr_un addr;
    sockfd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (sockfd < 0) {
        perror("socket");
        return -1;
    }
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCKET_PATH, sizeof(addr.sun_path) - 1);
    if (connect(sockfd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("connect");
        close(sockfd);
        return -1;
    }
    return sockfd;
}

void print_raw_frames(char *dat, size_t len) {
  int pos = 0;

  while(pos < len) {
    // find frame start
    if(dat[pos] == 0xCA && dat[pos+1] == 0xA0) {
      printf("\n");
    }

    printf("%02X ", dat[pos++]);
  }
}


int main(int argc, char *argv[]) {
    char buf[READ_BUF_SIZE];
    size_t bytes_read;
    int sockfd = -1;
    char cmd[3];
    int opt;
    int is_decode = 0;
    int is_print = 1;
    int pos = 0;


    while ((opt = getopt(argc, argv, "un")) != -1) {
        switch (opt) {
            case 'u':
                is_decode = 1;
                break;
            case 'n':
                is_print = 0;
                break;
            default:
                fprintf(stderr, "Usage: %s [-d]\n", argv[0]);
                fprintf(stderr, "      -u : unpack frame\n");
                fprintf(stderr, "      -n : no output\n");
                fprintf(stderr, "\n");
                exit(EXIT_FAILURE);
        }
    }

    sockfd = connect_to_server();

    if (sockfd < 0) {
         exit(1);
    }

    cmd[0] = 0x1F;

    write(sockfd, cmd, 1);
    read(sockfd, buf, 2);
    close(sockfd);

    while (1) {
        sockfd = connect_to_server();

        if (sockfd < 0) {
            printf("retry connect to server\n");
            continue;
        }

        uint16_t getsize = sizeof(buf)-pos;

        cmd[0] = 0x80;
        cmd[1] = (getsize >> 8) & 0xff;
        cmd[2] = getsize & 0xff;
        write(sockfd, cmd, 3);

        bytes_read = read(sockfd, &buf[pos], getsize) ;

        if (bytes_read < 0) {
            perror("read");
        } else if (bytes_read == 0) {
            //printf("close sever, retry.\n");
        } else {
            if (is_print) {
              if (is_decode) {
                pos = flexray_unpack(buf, bytes_read + pos);

                #if 1
                if (pos > 0) {
                  printf("pos=%d : ", pos);
                  for(int i=0; i<pos;i++)
                    printf("%02x ", buf[i]);
                  printf("\n");
                }
                #endif

              } else {
                print_raw_frames(buf, bytes_read);
              }
            } else {
              printf("recv %zd bytes\n", bytes_read);
            }
        }
        close(sockfd);
    }
    return 0;
}

