#ifndef YDA_DECK_LOADER_H
#define YDA_DECK_LOADER_H
#include "card_database.h"
#include <istream>
#include <map>
#include <vector>
namespace yda {
struct Deck {
    std::vector<uint32_t> main;
    std::vector<uint32_t> extra;
    std::vector<uint32_t> side;
};
using RequiredMain = std::map<uint32_t, unsigned>;
Deck parse_ydk(std::istream& input);
Deck load_ydk(const std::filesystem::path& path);
// 테스트용 구조 검증. 날짜별 금제/대회 참가 가능 여부를 보장하지 않는다.
void validate_deck(const Deck& deck, const CardDatabase& db,
                   const RequiredMain& required = {});
}
#endif
