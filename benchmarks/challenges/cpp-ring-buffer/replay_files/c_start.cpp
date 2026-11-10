#include "ring_buffer.h"

RingBuffer::RingBuffer(std::size_t capacity) : data_(capacity) {}

/* #defer members
push, pop, size, full: head_ is the oldest element
#end */
