// RUN: %clang_builtins -fexceptions -c %s -o %t.o
// RUN: %clangxx_builtins %S/gcc_personality_test_helper.cxx %t.o %librt -o %t
// RUN: %run %t

#include <stdlib.h>
#include <stdio.h>

extern void foo_clean(void* x);
extern void bar_clean(void* x);
extern void register_foo_local(int* x);
extern void register_bar_local(int* x);
extern void done_foo(void);
extern void done_bar(void);


/*
 * foo() is called by main() in gcc_personality_test_helper.cxx.
 * done_bar() is implemented in C++ and will throw an exception.
 * main() will catch the exception and verify that the cleanup
 * routines for foo() and bar() were called by the personality
 * function.
 */

void bar() {
    int x __attribute__((cleanup(bar_clean))) = 0;
    register_bar_local(&x);
    done_bar();
}

void foo() {
    int x __attribute__((cleanup(foo_clean))) = 0;
    register_foo_local(&x);
    bar();
    done_foo();
}
