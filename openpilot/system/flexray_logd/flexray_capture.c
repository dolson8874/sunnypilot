#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "flexray_common.h"
#include "flexray_capture.h"
#include "flexray_decoder.h"
#include "flexray_output.h"
#include "flexray_reader.h"

static volatile sig_atomic_t interrupted;
static void stop_capture(int signal_number) {
  (void)signal_number;
  interrupted = 1;
}

int flexray_capture_main(int argc, char **argv, bool serve_socket) {
  const char *input = NULL, *directory = serve_socket ? getenv("FLEXRAY_LOG_DIR") : ".";
  const char *socket_path = SOCKET_PATH;
  bool loop = false, decode = serve_socket;
  size_t rotate_bytes = 64 * 1024 * 1024;
  int option;
  while ((option = getopt(argc, argv, "f:lo:m:p:sh")) != -1) {
    switch (option) {
      case 'f': input = optarg; break;
      case 'l': loop = true; break;
      case 'o': directory = optarg; break;
      case 'p': socket_path = optarg; break;
      case 's': decode = false; break;
      case 'm': {
        char *end;
        errno = 0;
        unsigned long long size = strtoull(optarg, &end, 10);
        if (errno || *end || !size || optarg[0] == '-' || size > SIZE_MAX) {
          fprintf(stderr, "flexray: invalid segment size\n");
          return EXIT_FAILURE;
        }
        rotate_bytes = size;
        break;
      }
      default:
        fprintf(stderr, "Usage: %s [-f FILE] [-l] [-s] [-o DIRECTORY] [-m SEGMENT_BYTES] [-p SOCKET]\n"
                        "  -f: replay once; -l: loop replay; -s: raw socket output\n"
                        "  -o: raw recording directory; -m: rotate bytes (default 67108864)\n"
                        "  FLEXRAY_LOG_DIR: optional daemon recording directory\n", argv[0]);
        return option == 'h' ? EXIT_SUCCESS : EXIT_FAILURE;
    }
  }
  if (optind != argc || (loop && !input)) {
    fprintf(stderr, "flexray: unexpected arguments or -l without -f\n");
    return EXIT_FAILURE;
  }
  struct sigaction action = {.sa_handler = stop_capture};
  sigemptyset(&action.sa_mask);
  if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) {
    perror("flexray: sigaction");
    return EXIT_FAILURE;
  }
  interrupted = 0;
  struct flexray_reader reader;
  if (flexray_reader_open(&reader, input, loop)) {
    perror("flexray: input");
    return EXIT_FAILURE;
  }
  struct flexray_output socket_output = {0}, file_output = {0};
  int result = EXIT_FAILURE;
  bool recording_failed = false;
  uint64_t recording_skipped = 0;
  if (directory && flexray_output_start(&file_output, directory, false, rotate_bytes)) {
    perror("flexray: recording startup");
    if (!serve_socket) goto cleanup;
    recording_failed = true;
    fprintf(stderr, "flexray: recording disabled; capture/socket continue\n");
  }
  if (serve_socket && flexray_output_start(&socket_output, socket_path, true, 0)) {
    perror("flexray: socket startup");
    goto cleanup;
  }
  char raw[SPI_CHUNK_SIZE], pending[SPI_CHUNK_SIZE + 266], decoded[SPI_CHUNK_SIZE + 266];
  size_t pending_size = 0;
  struct flexray_decode_stats stats = {0};
  uint64_t raw_bytes = 0;
  result = EXIT_SUCCESS;
  while (!interrupted) {
    if (file_output.started && atomic_load(&file_output.error)) {
      if (flexray_output_close(&file_output)) perror("flexray: recording disabled; capture continues");
      recording_failed = true;
    }
    if (socket_output.started && atomic_load(&socket_output.error)) {
      result = EXIT_FAILURE;
      break;
    }
    ssize_t n = flexray_reader_read(&reader, raw, sizeof(raw));
    if (n < 0) {
      if (interrupted) break;
      perror("flexray: input read");
      result = EXIT_FAILURE;
      break;
    }
    if (!n) {
      if (reader.type == FT_FILE_TEST) break;
      usleep(1000);
      continue;
    }
    raw_bytes += n;
    if (file_output.started && flexray_output_push(&file_output, raw, n)) {
      recording_skipped += n;
      if (flexray_output_close(&file_output)) perror("flexray: recording disabled; capture continues");
      recording_failed = true;
    } else if (directory && !file_output.started) {
      recording_skipped += n;
    }
    if (socket_output.started) {
      const void *data = raw;
      size_t size = n;
      if (decode) {
        if (pending_size + size > sizeof(pending)) {
          fprintf(stderr, "flexray: decoder pending overflow\n");
          result = EXIT_FAILURE;
          break;
        }
        memcpy(pending + pending_size, raw, size);
        pending_size += size;
        size = decode_flexray_buffer_stats(pending, &pending_size, decoded, sizeof(decoded), &stats);
        data = decoded;
      }
      if (size && flexray_output_push(&socket_output, data, size)) {
        fprintf(stderr, "flexray: socket worker failed\n");
        result = EXIT_FAILURE;
        break;
      }
    }
    // Preserve the previous nominal replay rate; it is not an original receive timestamp.
    if (loop) usleep((useconds_t)((size_t)n * 0.8));
  }
  fprintf(stderr, "flexray: input=%llu frames=%llu header_crc=%llu payload_crc=%llu metadata=%llu noise=%llu trailing=%zu\n",
          (unsigned long long)raw_bytes, (unsigned long long)stats.frames,
          (unsigned long long)stats.header_crc_errors, (unsigned long long)stats.payload_crc_errors,
          (unsigned long long)stats.metadata_errors, (unsigned long long)stats.noise_bytes, pending_size);
  // Bounded socket drain; raw file output always drains its complete queued bytes.
  if (socket_output.started) {
    for (int i = 0; i < 100; ++i) {
      pthread_mutex_lock(&socket_output.queue.mutex);
      bool empty = socket_output.queue.count == 0;
      pthread_mutex_unlock(&socket_output.queue.mutex);
      if (empty) break;
      usleep(10000);
    }
  }
cleanup:
  flexray_reader_close(&reader);
  if (flexray_output_close(&socket_output)) { perror("flexray: socket shutdown"); result = EXIT_FAILURE; }
  if (flexray_output_close(&file_output)) { perror("flexray: recording shutdown"); recording_failed = true; }
  if (recording_failed || file_output.dropped_bytes) {
    fprintf(stderr, "flexray: recording incomplete; capture continued, disabled_recording_skipped=%llu bytes\n",
            (unsigned long long)recording_skipped);
    result = EXIT_FAILURE;  // Report an incomplete recording only when capture itself ends.
  }
  return result;
}
