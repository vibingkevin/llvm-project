// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// No argument: a fresh condition variable times out normally.
// Any argument: perform a monotonic clockwait before the realtime timedwait.
// Run with an external timeout: affected ROMs hang in the second operation.
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

static pthread_cond_t cv = PTHREAD_COND_INITIALIZER;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;

static void dump(const char *tag) {
  unsigned words[sizeof(cv) / sizeof(unsigned)];
  memcpy(words, &cv, sizeof words);
  printf("%s", tag);
  for (unsigned i = 0; i < sizeof words / sizeof words[0]; ++i)
    printf(" %08x", words[i]);
  puts("");
}

static struct timespec deadline(clockid_t clock) {
  struct timespec value;
  clock_gettime(clock, &value);
  value.tv_nsec += 50000000;
  if (value.tv_nsec >= 1000000000) {
    ++value.tv_sec;
    value.tv_nsec -= 1000000000;
  }
  return value;
}

int main(int argc, char **argv) {
  (void)argv;
  setbuf(stdout, NULL);
  pthread_mutex_lock(&mutex);
  dump("initial");
  if (argc > 1) {
    struct timespec value = deadline(CLOCK_MONOTONIC);
    int result = pthread_cond_clockwait(&cv, &mutex, CLOCK_MONOTONIC, &value);
    printf("clockwait-monotonic=%d\n", result);
    dump("after-clockwait");
    if (result != ETIMEDOUT)
      return 1;
  }
  struct timespec value = deadline(CLOCK_REALTIME);
  printf("timedwait-realtime deadline=%lld.%09ld\n",
         (long long)value.tv_sec, value.tv_nsec);
  int result = pthread_cond_timedwait(&cv, &mutex, &value);
  printf("timedwait=%d\n", result);
  dump("final");
  pthread_mutex_unlock(&mutex);
  return result == ETIMEDOUT ? 0 : 1;
}
