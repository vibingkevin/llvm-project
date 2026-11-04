// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Drop root privileges before filesystem permission tests, then exec the test.
#include <errno.h>
#include <grp.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {
  if (argc < 3) {
    fprintf(stderr, "usage: ohos-run-as UID command [args...]\n");
    return 125;
  }
  char *end;
  errno = 0;
  unsigned long value = strtoul(argv[1], &end, 10);
  if (errno || *end || value == 0 || value != (uid_t)value) return 125;
  if (setgroups(0, NULL) || setgid((gid_t)value) || setuid((uid_t)value)) {
    perror("drop test privileges");
    return 125;
  }
  execvp(argv[2], argv + 2);
  perror("exec test");
  return 125;
}
