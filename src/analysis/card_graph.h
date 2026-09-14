#ifndef YDA_CARD_GRAPH_H
#define YDA_CARD_GRAPH_H

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>
#include "card_analyzer.h"

namespace yda {
enum class RelationStrength : uint8_t { Strong, Medium, Weak };

const char* relation_strength_name(RelationStrength strength) noexcept;

struct RelationEvidence {
    uint32_t required_code = 0;
    RelationStrength strength = RelationStrength::Weak;
    std::string kind;
    std::string detail;
    int score = 0;
};

struct CandidateCard {
    uint32_t code = 0;
    std::string name;
    int score = 0;
    std::string pool; // REQUIRED / ENGINE / GENERIC
    std::vector<CardFeature> features;
    std::vector<RelationEvidence> relations;
};

struct CandidatePoolConfig {
    size_t engine_limit = 80;
    size_t generic_limit = 40;
    size_t total_limit = 120;
    int strong_weight = 100;
    int medium_weight = 20;
    int weak_weight = 3;
};

struct CandidatePool {
    std::vector<uint32_t> required;
    std::vector<CandidateCard> cards;
};

class CardGraphBuilder {
public:
    CandidatePool build(const CardDatabase& database,
                        const std::vector<uint32_t>& required,
                        const CandidatePoolConfig& config = {}) const;
private:
    CardAnalyzer analyzer_;
};
}
#endif
