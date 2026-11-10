#include <cstddef>

/* #defer process_data
Validate the buffer, then process the data.
#end */

int main() {
    return process_data(nullptr, 0);
}

/* #wait
The first idea allocated a scratch copy. Not needed: fold in place.
#end */

/* #evolve process_data
int process_data(const unsigned char* buffer, std::size_t size) {
    if (!buffer) return 0;
    int checksum = 0;
    for (std::size_t i = 0; i < size; ++i) checksum ^= buffer[i];
    return checksum;
}
#end */
