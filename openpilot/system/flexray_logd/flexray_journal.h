#ifndef FLEXRAY_JOURNAL_H
#define FLEXRAY_JOURNAL_H
#include <stdint.h>

struct flexray_journal;
// Best-effort sidecar only; producers never perform file writes or wait for disk.
struct flexray_journal *flexray_journal_open(const char *directory);
void flexray_journal_gap(struct flexray_journal *journal, const char *reason, uint64_t offset,
                         uint64_t size, uint64_t written, int error);
void flexray_journal_segment(struct flexray_journal *journal, const char *name, uint64_t written);
void flexray_journal_status(struct flexray_journal *journal, uint64_t *lost, int *error);
void flexray_journal_close(struct flexray_journal *journal);
#endif
