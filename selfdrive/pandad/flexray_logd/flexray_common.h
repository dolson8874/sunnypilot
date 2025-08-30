#ifndef FLEXRAY_COMMON_H
#define FLEXRAY_COMMON_H

//#define SPI_CHUNK_SIZE 16384
#define SPI_CHUNK_SIZE 32768
#define SPI_BUFFER_SIZE 0x20000
#define SOCKET_PATH   "/tmp/flexraylogd_unix_socket"

#define MAX_SEND_SIZE (0x4000U)

#define BUFFER_FREE(write, read, size) \
    (((read) > (write)) ? ((read) - (write) - 1) : ((size) - (write) + (read) - 1))


#endif

