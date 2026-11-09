#ifndef FLEXRAY_DECODER_H
#define FLEXRAY_DECODER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


struct __attribute__((packed)) can_header {
  uint8_t reserved : 1;
  uint8_t bus : 3;
  uint8_t data_len_code : 4;
  uint8_t rejected : 1;
  uint8_t returned : 1;
  uint8_t extended : 1;
  uint32_t addr : 29;
  uint8_t checksum : 8;
};

// max 265 = header (6) + flags (1) + counter(1) + data (254)  + CRC(3)
// FPAGA -> COMMA (BIG ENDIAN-> LITTLE)
struct __attribute__((packed)) flexray_header {
  uint8_t           : 1;
  uint8_t extended  : 1;
  uint8_t returned  : 1;
  uint8_t rejected  : 1;
  uint8_t bus       : 3;
  uint8_t reserved  : 1;

  uint8_t  flagsid  : 8; // 5bit
  uint16_t frame_id : 8; // need make bit (flasgsid & 0x7) << 8 | frame_id

  uint8_t crc_msb   : 1;
  uint8_t length    : 7;
  uint8_t crc       : 8;
  uint8_t counter   : 6;
  uint8_t crc_lsb   : 2;

  // flags          : 8;      // for cabana
  // counter        : 8;      // for cabana
  //unsigned char   data[254];  //  add flags + counter + data
  //unsigned int    crc       : 24;
};


struct flexray_decode_stats {
  uint64_t frames, noise_bytes, padding_bytes, header_crc_errors, payload_crc_errors, metadata_errors;
  // Index 0: wire bus 0 (BCM-side -> DADC), index 1: wire bus 2 (DADC -> BCM).
  uint64_t direction_frames[2], direction_wire_bytes[2], resyncs;
  bool recovering;
};

size_t decode_flexray_buffer_stats(char *data, size_t *size, char *out, size_t capacity,
                                   struct flexray_decode_stats *stats);

uint8_t calculate_flexray_checksum(uint8_t *header, uint16_t fid);

size_t decode_flexray_buffer(char *data, size_t *psize, char *out, size_t out_size);

#endif
