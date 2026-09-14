#ifndef YDA_CARD_ANALYZER_H
#define YDA_CARD_ANALYZER_H

#include <cstdint>
#include <string>
#include <vector>
#include "data/card_database.h"

namespace yda {
enum class CardFeature : uint8_t {
    Search,
    Draw,
    SpecialSummon,
    NormalSummon,
    Negate,
    Destroy,
    Banish,
    Return,
    SendToGY,
    Recover,
    Material,
    Token,
    Protection,
    Discard,
    Trigger,
    Target,
};

const char* feature_name(CardFeature feature) noexcept;

struct FeatureEvidence {
    CardFeature feature{};
    std::string evidence;
};

struct CardAnalysis {
    uint32_t code = 0;
    std::string name;
    std::vector<FeatureEvidence> features;
    std::vector<std::string> conditions;
    std::vector<std::string> costs;
    std::vector<std::string> zones;
};

class CardAnalyzer {
public:
    CardAnalysis analyze(const CardRecord& card) const;
    static bool has_feature(const CardAnalysis& analysis, CardFeature feature) noexcept;
};
}
#endif
