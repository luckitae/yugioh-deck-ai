#ifndef YDA_SMOKE_RESPONSE_H
#define YDA_SMOKE_RESPONSE_H
#include "message_decoder.h"
#include <stdexcept>
#include <string>
#include <vector>
namespace yda {
constexpr uint32_t hinotama_code = 46130346;
constexpr uint32_t max_selection_candidates = 4096;
enum class SmokePolicy { Pass, Hinotama };
struct ProtocolError : std::runtime_error { using std::runtime_error::runtime_error; };
struct UnsupportedSelection : std::runtime_error { using std::runtime_error::runtime_error; };
struct Response {
    uint32_t prompt = 0;
    uint32_t activated_code = 0;
    std::vector<uint8_t> bytes;
};
uint32_t read_u32(const uint8_t* bytes);
void append_u32(std::vector<uint8_t>& out, uint32_t value);
bool is_selection(uint32_t type);
Response smoke_response(const DecodedMessage& message, SmokePolicy policy);
}
#endif
