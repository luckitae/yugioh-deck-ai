#ifndef YDA_CARD_DATABASE_H
#define YDA_CARD_DATABASE_H

#include <array>
#include <cstdint>
#include <filesystem>
#include <map>
#include <string>
#include "ocgapi_types.h"

namespace yda {
struct CardRecord {
    OCG_CardData data{};
    std::array<uint16_t, 5> setcodes{};
    uint32_t scope = 0;
    uint64_t category = 0;
    std::string name;
    std::string text;
};

// DB는 듀얼 전에 한 번 읽고, 모든 듀얼이 파괴될 때까지 유지한다.
// 노드 주소와 setcodes 배열의 주소가 바뀌지 않도록 복사/이동을 금지한다.
class CardDatabase {
public:
    explicit CardDatabase(const std::filesystem::path& path);
    CardDatabase(const CardDatabase&) = delete;
    CardDatabase& operator=(const CardDatabase&) = delete;
    CardDatabase(CardDatabase&&) = delete;
    CardDatabase& operator=(CardDatabase&&) = delete;
    const CardRecord* find(uint32_t code) const noexcept;
    const std::map<uint32_t, CardRecord>& records() const noexcept { return cards_; }
    size_t size() const noexcept { return cards_.size(); }
private:
    std::map<uint32_t, CardRecord> cards_;
};

struct CardReaderContext {
    const CardDatabase& database;
    uint64_t reads = 0;
    uint64_t done = 0;
    bool failed = false;
    uint32_t missing_code = 0;
    static void read(void* payload, uint32_t code, OCG_CardData* out) noexcept;
    static void release(void* payload, OCG_CardData* data) noexcept;
};
}
#endif
