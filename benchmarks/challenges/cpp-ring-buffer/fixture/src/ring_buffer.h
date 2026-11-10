#pragma once
#include <cstddef>
#include <vector>

// Fixed-capacity FIFO queue of ints.
class RingBuffer {
public:
    explicit RingBuffer(std::size_t capacity);
    bool push(int value);       // returns false (and stores nothing) when full
    bool pop(int& out);         // oldest element first; returns false when empty
    std::size_t size() const;   // number of stored elements
    bool full() const;

private:
    std::vector<int> data_;
    std::size_t head_ = 0;      // index of the oldest element
    std::size_t count_ = 0;
};
