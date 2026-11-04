// REQUIRES: crt

// RUN: %clangxx -g -fno-exceptions -DCRT_SHARED -c %s -fPIC -o %tshared.o
// RUN: %clangxx -g -fno-exceptions -c %s -fPIC -o %t.o
// RUN: %clangxx -g -shared -Wl,-soname,dso_handle_test.so -o %T/dso_handle_test.so -nostdlib %crti %crtbegin %tshared.o %libstdcxx %libc -lm %libgcc %crtend %crtn
// RUN: %clangxx -g -o %t -fno-pic -no-pie -nostdlib %crt1 %crti %crtbegin %t.o %libstdcxx %libc -lm %libgcc %T/dso_handle_test.so -Wl,-rpath,'$ORIGIN' %crtend %crtn
// RUN: %run %t 2>&1 | FileCheck %s

// UNSUPPORTED: target={{arm.*}}, target={{aarch64.*}} && !ohos

#include <stdio.h>

// CHECK: 1
// CHECK-NEXT: ~A()

#ifdef CRT_SHARED
bool G;
void C() {
  printf("%d\n", G);
}

struct A {
  A() { G = true; }
  ~A() {
    printf("~A()\n");
  }
};

A a;
#else
void C();

int main() {
  C();
  return 0;
}
#endif
