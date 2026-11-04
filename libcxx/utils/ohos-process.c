// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Preserve waitpid's signal result for host-side `not --crash` checks.
#include <errno.h>
#include <stdio.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

int main(int argc, char **argv) {
  if (argc < 3) return 125;
  pid_t child = fork();
  if (child < 0) return 125;
  if (!child) {
    execvp(argv[2], argv + 2);
    perror("execvp");
    _exit(127);
  }
  int status;
  while (waitpid(child, &status, 0) < 0)
    if (errno != EINTR) return 125;
  FILE *file = fopen(argv[1], "w");
  if (!file) return 125;
  int signal = WIFSIGNALED(status) ? WTERMSIG(status) : 0;
  fprintf(file, "%d", signal);
  if (fclose(file)) return 125;
  return signal ? 128 + signal : WEXITSTATUS(status);
}
