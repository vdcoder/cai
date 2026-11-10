#include "ring_buffer.h"

RingBuffer::RingBuffer(std::size_t capacity) : data_(capacity) {}

bool RingBuffer::push(int value) {
    if (full()) return false;
    data_[(head_ + count_) % data_.size()] = value;
    ++count_;
    return true;
}

bool RingBuffer::pop(int& out) {
    if (count_ == 0) return false;
    out = data_[head_];
    head_ = (head_ + 1) % data_.size();
    --count_;
    return true;
}

std::size_t RingBuffer::size() const { return count_; }

bool RingBuffer::full() const { return count_ == data_.size(); }
