#include "ring_buffer.h"

RingBuffer::RingBuffer(std::size_t capacity) : data_(capacity) {}

// TODO: implement the four members below.
bool RingBuffer::push(int) { return false; }
bool RingBuffer::pop(int&) { return false; }
std::size_t RingBuffer::size() const { return 0; }
bool RingBuffer::full() const { return false; }
