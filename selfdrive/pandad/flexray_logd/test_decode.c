#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <errno.h>

#include "flexray_common.h"
#include "flexray_decoder.h"
#include "flexray_unpack.h"

volatile int do_exit = 0;
FILE *fd;

static void
sigintHandler(int signum) {
    do_exit = 1;
    if (fd) fclose(fd);
    fprintf(stderr, "\nexit\n");
}


int main(int argc, char *argv[]) {
  char *filename= NULL;
  int opt;
  char buf[SPI_CHUNK_SIZE];
  char out[SPI_CHUNK_SIZE];
  size_t out_size = 0, pos = 0;


  while ((opt = getopt(argc, argv, "f:")) != -1) {
    switch (opt) {
      case 'f':
          filename = optarg;
          break;
      default:
          fprintf(stderr, "Usage: %s [-f]\n", argv[0]);
          fprintf(stderr, "      -f : file open data\n");
          fprintf(stderr, "\n");
          exit(EXIT_FAILURE);
    }
  }

  fd = fopen(filename, "rb");

  if (!fd) {
    fprintf(stderr, "fail file open (%s)\n", filename);
    return 0;
  }

  signal(SIGINT, sigintHandler);
  signal(SIGKILL, sigintHandler);
  signal(SIGPIPE, SIG_IGN);

  while (!do_exit) {
    size_t cp_size = 0;
    size_t bytes = 0;

    bytes = fread(&buf[out_size], 1, SPI_CHUNK_SIZE-out_size, fd);
    if (bytes <= 0) {
      if (feof(fd))
          break;
    }

    out_size += bytes;

    printf("buf=%p out=%p out_size=%zu\n", buf, out, out_size);

    if (out_size < 6) { 
      continue;
    }

    cp_size = decode_flexray_buffer(buf, &out_size, &out[pos]);

    pos = flexray_unpack(out, cp_size + pos);
  }

  fclose(fd);

  signal(SIGINT, SIG_DFL);
  signal(SIGPIPE, SIG_DFL);
}

