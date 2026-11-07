#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "flexray_decoder.h"

// Independent bitwise reference matching the FPGA; no C wire-format bitfields.
static uint32_t crc_bits(uint32_t crc, uint32_t value, unsigned count, unsigned width, uint32_t poly) {
  for (int bit = count - 1; bit >= 0; --bit) {
    unsigned feedback = ((crc >> (width - 1)) ^ (value >> bit)) & 1;
    crc = (crc << 1) & ((1U << width) - 1);
    if (feedback) crc ^= poly;
  }
  return crc;
}

static size_t make_frame(char *data, uint16_t id, uint8_t flags, uint8_t counter, uint8_t words) {
  uint8_t *p = (uint8_t *)data;
  uint32_t hcrc = crc_bits(0x1a, ((flags & 3U) << 18) | (id << 7) | words, 20, 11, 0x385);
  p[0] = 0xca; p[1] = 0xa0;
  p[2] = (flags << 3) | (id >> 8); p[3] = id;
  p[4] = (words << 1) | (hcrc >> 10); p[5] = hcrc >> 2;
  p[6] = ((hcrc & 3U) << 6) | counter;
  p[7] = flags; p[8] = counter;
  size_t size = words * 2;
  for (size_t i = 0; i < size; ++i) p[9 + i] = i;
  uint32_t crc = 0xfedcba;
  for (size_t i = 2; i < 7; ++i) crc = crc_bits(crc, p[i], 8, 24, 0x5d6dcb);
  for (size_t i = 0; i < size; ++i) crc = crc_bits(crc, p[9 + i], 8, 24, 0x5d6dcb);
  p[9 + size] = crc >> 16; p[10 + size] = crc >> 8; p[11 + size] = crc;
  return size + 12;
}

static void check_output(const char *output, const char *frame, uint16_t id, size_t size) {
  const uint8_t *p = (const uint8_t *)output;
  uint32_t address = (uint32_t)p[1] | ((uint32_t)p[2] << 8) | ((uint32_t)p[3] << 16) | ((uint32_t)p[4] << 24);
  assert((address >> 3) == id);
  assert(p[0] == 4);
  assert(p[5] == ((uint8_t)frame[4] >> 1));
  assert(memcmp(output + 6, frame + 7, size - 7) == 0);
}

int main(void) {
  char frame[266], input[600], output[600];
  size_t size = make_frame(frame, 0x7ff, 31, 63, 127);
  for (size_t split = 0; split < size; ++split) {
    memcpy(input, frame, split);
    size_t pending = split;
    assert(decode_flexray_buffer(input, &pending, output, sizeof(output)) == 0);
    assert(pending == split);
    memcpy(input + pending, frame + split, size - split);
    pending += size - split;
    assert(decode_flexray_buffer(input, &pending, output, sizeof(output)) == size - 1);
    assert(pending == 0);
    check_output(output, frame, 0x7ff, size);
  }
  for (uint16_t id = 0; id < 2048; ++id) {
    for (uint8_t flags = 0; flags < 32; ++flags) {
      size = make_frame(frame, id, flags, id % 64, id % 128);
      memcpy(input, frame, size);
      size_t pending = size;
      assert(decode_flexray_buffer(input, &pending, output, sizeof(output)) == size - 1);
      assert(pending == 0);
      check_output(output, frame, id, size);
    }
  }
  size = make_frame(frame, 15, 3, 7, 2);
  memcpy(input, frame, size);
  size_t pending = size;
  assert(decode_flexray_buffer(input, &pending, output, size - 2) == 0);
  assert(pending == size);
  assert(decode_flexray_buffer(input, &pending, output, size - 1) == size - 1);
  // Each corrupt candidate must be rejected, without hiding the next valid frame.
  for (size_t byte = 2; byte < size; ++byte) {
    memcpy(input, frame, size);
    input[byte] ^= 1;
    memcpy(input + size, frame, size);
    pending = size * 2;
    struct flexray_decode_stats stats = {0};
    assert(decode_flexray_buffer_stats(input, &pending, output, sizeof(output), &stats) == size - 1);
    assert(pending == 0);
    assert(stats.frames == 1);
    assert(stats.header_crc_errors + stats.payload_crc_errors + stats.metadata_errors > 0);
  }
  puts("decoder: all 2048 IDs/32 flags, lengths, split frames, CRC24, metadata and recovery OK");
  return 0;
}
