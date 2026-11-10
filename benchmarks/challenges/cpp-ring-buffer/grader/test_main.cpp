#include "ring_buffer.h"
#include <cstdio>

static int failures = 0;
#define CHECK(name, cond) do { if (!(cond)) { std::printf("FAIL %s\n", name); ++failures; } } while (0)

int main() {
    { RingBuffer rb(3); CHECK("starts_empty", rb.size() == 0 && !rb.full()); int v; CHECK("pop_empty", !rb.pop(v)); }
    { RingBuffer rb(2); CHECK("push", rb.push(1) && rb.push(2) && rb.full() && rb.size() == 2);
      CHECK("push_full", !rb.push(3) && rb.size() == 2); }
    { RingBuffer rb(3); int a = 0, b = 0, c = 0, d = 0; rb.push(1); rb.push(2); rb.push(3); rb.pop(a); rb.push(4);
      rb.pop(b); rb.pop(c); rb.pop(d); CHECK("fifo_wrap", a == 1 && b == 2 && c == 3 && d == 4 && rb.size() == 0); }
    { RingBuffer rb(1); int v = 0; bool ok = true;
      for (int i = 0; i < 100; ++i) { ok = ok && rb.push(i) && rb.pop(v) && v == i; } CHECK("many_cycles", ok); }
    { RingBuffer rb(0); CHECK("zero_capacity", !rb.push(1) && rb.size() == 0); }
    return failures ? 1 : 0;
}
