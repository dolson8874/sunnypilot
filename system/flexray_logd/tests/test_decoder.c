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
  assert(p[0] == ((((uint8_t)frame[1] >> 4) & 7) << 1));
  assert(p[5] == ((uint8_t)frame[4] >> 1));
  assert(memcmp(output + 6, frame + 7, size - 7) == 0);
}

static void frame_crc(char *frame, size_t size) {
  uint8_t *p = (uint8_t *)frame;
  uint32_t crc = 0xfedcba;
  for (size_t i = 2; i < 7; ++i) crc = crc_bits(crc, p[i], 8, 24, 0x5d6dcb);
  for (size_t i = 9; i < size - 3; ++i) crc = crc_bits(crc, p[i], 8, 24, 0x5d6dcb);
  p[size - 3] = crc >> 16; p[size - 2] = crc >> 8; p[size - 1] = crc;
}

static void test_bidirectional(void) {
  char frame[266], input[2048], output[2048];
  for (unsigned bus = 0; bus <= 2; bus += 2) {
    for (unsigned words = 0; words <= 127; ++words) {
      size_t size = make_frame(frame, 0x47f, 31, 63, words);
      frame[1] = 0x80 | (bus << 4);
      if (words >= 2) {
        memcpy(frame + 9, "\xca\xa0\xca\x80", 4);
        frame_crc(frame, size);
      }
      for (size_t split = 0; split <= size; ++split) {
        struct flexray_decode_stats stats = {0};
        memcpy(input, frame, split);
        size_t pending = split;
        size_t n = decode_flexray_buffer_stats(input, &pending, output, sizeof(output), &stats);
        if (split < size) {
          assert(n == 0 && pending == split);
          memcpy(input + pending, frame + split, size - split);
          pending += size - split;
          n = decode_flexray_buffer_stats(input, &pending, output, sizeof(output), &stats);
        }
        assert(n == size - 1 && pending == 0);
        check_output(output, frame, 0x47f, size);
        assert(stats.direction_frames[bus == 2] == 1);
        assert(stats.direction_wire_bytes[bus == 2] == size);
        assert(stats.resyncs == 0 && stats.noise_bytes == 0 && stats.padding_bytes == 0);
      }
    }
  }
  size_t size = make_frame(frame, 15, 3, 7, 2);
  for (unsigned marker = 0; marker < 256; ++marker) {
    memcpy(input, frame, size);
    input[1] = marker;
    size_t pending = size;
    size_t n = decode_flexray_buffer(input, &pending, output, sizeof(output));
    assert(n == ((marker == 0x80 || marker == 0xa0) ? size - 1 : 0));
  }
  // The same ID on both directions stays separate, with zero padding excluded.
  memset(input, 0, 3);
  memcpy(input + 3, frame, size);
  memcpy(input + 3 + size, frame, size);
  input[4 + size] = 0x80;
  memset(input + 3 + size * 2, 0, 5);
  size_t pending = 8 + size * 2;
  struct flexray_decode_stats stats = {0};
  assert(decode_flexray_buffer_stats(input, &pending, output, sizeof(output), &stats) == (size - 1) * 2);
  assert(pending == 0 && stats.padding_bytes == 8 && stats.resyncs == 0);
  assert(stats.direction_frames[0] == 1 && stats.direction_frames[1] == 1);
  assert(output[0] == 4 && output[size - 1] == 0);
  memcpy(input, frame, size);
  memcpy(input + size, frame, size);
  input[size + 1] = 0x80;
  pending = size * 2;
  stats = (struct flexray_decode_stats){0};
  assert(decode_flexray_buffer_stats(input, &pending, output, size - 1, &stats) == size - 1);
  assert(pending == size && stats.frames == 1);
  assert(decode_flexray_buffer_stats(input, &pending, output, size - 1, &stats) == size - 1);
  assert(pending == 0 && output[0] == 0 && stats.frames == 2 && stats.resyncs == 0);
  // CRC/metadata corruption, insertion, deletion and nonpadding junk all recover.
  for (unsigned kind = 0; kind < 5; ++kind) {
    memcpy(input, frame, size);
    size_t damaged = size;
    if (kind == 0) input[3] ^= 1;
    if (kind == 1) input[size - 1] ^= 1;
    if (kind == 2) input[7] ^= 1;
    if (kind == 3) { memmove(input + 11, input + 10, size - 10); input[10] = 0x55; damaged++; }
    if (kind == 4) { memmove(input + 10, input + 11, size - 11); damaged--; }
    memcpy(input + damaged, frame, size);
    pending = damaged + size;
    stats = (struct flexray_decode_stats){0};
    assert(decode_flexray_buffer_stats(input, &pending, output, sizeof(output), &stats) == size - 1);
    assert(stats.frames == 1 && stats.resyncs == 1);
    assert(stats.noise_bytes + stats.padding_bytes + stats.direction_wire_bytes[1] + pending == damaged + size);
    assert(stats.header_crc_errors + stats.payload_crc_errors + stats.metadata_errors > 0);
  }
  // Across byte-at-a-time reads, padding isn't a resync and final CA is retained.
  pending = 0;
  stats = (struct flexray_decode_stats){0};
  for (size_t i = 0; i < size; ++i) {
    input[pending++] = frame[i];
    size_t n = decode_flexray_buffer_stats(input, &pending, output, sizeof(output), &stats);
    assert(n == (i == size - 1 ? size - 1 : 0));
  }
  assert(stats.frames == 1 && stats.resyncs == 0);
  input[0] = 0; input[1] = 0xca; pending = 2;
  assert(decode_flexray_buffer_stats(input, &pending, output, 0, &stats) == 0);
  assert(pending == 1 && (uint8_t)input[0] == 0xca && stats.padding_bytes == 1);
  puts("decoder: both markers, all word lengths/splits, embedded markers, padding, damage recovery OK");
}

int main(void) {
  test_bidirectional();
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
