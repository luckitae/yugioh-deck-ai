#include "card_graph.h"
#include "ocgapi_constants.h"
#include <algorithm>
#include <cctype>
#include <set>
#include <stdexcept>
#include <string_view>

namespace yda {
namespace {
std::string lower_ascii(std::string_view input)
{
    std::string result;
    result.reserve(input.size());
    for(unsigned char ch : input)
        result.push_back(static_cast<char>(std::tolower(ch)));
    return result;
}

bool contains_name(const CardRecord& source, const CardRecord& target)
{
    if(target.name.size() < 4 || source.text.empty())
        return false;
    return lower_ascii(source.text).find(lower_ascii(target.name)) != std::string::npos;
}

bool setcode_matches(uint16_t set_code, uint16_t to_match)
{
    // OCGCore card::match_setcode와 같은 규칙: 하위 12비트 카드군 + 상위 sub-set 비트.
    return set_code != 0 && to_match != 0 &&
           (set_code & 0x0fffu) == (to_match & 0x0fffu) &&
           (set_code & to_match) == set_code;
}

bool setcode_overlap(const CardRecord& a, const CardRecord& b, uint16_t* shared = nullptr)
{
    for(const auto left : a.setcodes) {
        for(const auto right : b.setcodes) {
            if(setcode_matches(left, right) || setcode_matches(right, left)) {
                if(shared)
                    *shared = left;
                return true;
            }
        }
    }
    return false;
}

uint32_t summon_mask(uint32_t type)
{
    return type & (TYPE_FUSION | TYPE_RITUAL | TYPE_SYNCHRO | TYPE_XYZ | TYPE_PENDULUM | TYPE_LINK);
}

uint32_t broad_type(uint32_t type)
{
    if(type & TYPE_MONSTER) return TYPE_MONSTER;
    if(type & TYPE_SPELL) return TYPE_SPELL;
    if(type & TYPE_TRAP) return TYPE_TRAP;
    return 0;
}

bool same_monster_stat(uint32_t left_type, uint32_t right_type, uint64_t left, uint64_t right)
{
    return (left_type & TYPE_MONSTER) && (right_type & TYPE_MONSTER) && left != 0 && left == right;
}

std::vector<CardFeature> feature_list(const CardAnalysis& analysis)
{
    std::vector<CardFeature> out;
    out.reserve(analysis.features.size());
    for(const auto& feature : analysis.features)
        out.push_back(feature.feature);
    return out;
}

size_t feature_overlap(const CardAnalysis& a, const CardAnalysis& b)
{
    size_t count = 0;
    for(const auto& left : a.features)
        if(CardAnalyzer::has_feature(b, left.feature))
            ++count;
    return count;
}

bool generic_feature(CardFeature feature)
{
    switch(feature) {
    case CardFeature::Search:
    case CardFeature::Draw:
    case CardFeature::Negate:
    case CardFeature::Destroy:
    case CardFeature::Banish:
    case CardFeature::Protection:
    case CardFeature::Recover:
        return true;
    default:
        return false;
    }
}

int generic_utility_score(const CardAnalysis& analysis)
{
    int score = 0;
    for(const auto& feature : analysis.features)
        if(generic_feature(feature.feature))
            score += 10;
    return score;
}

void add_relation(CandidateCard& candidate, uint32_t required_code, RelationStrength strength,
                  const std::string& kind, const std::string& detail, int score)
{
    candidate.relations.push_back({required_code, strength, kind, detail, score});
    candidate.score += score;
}

bool better(const CandidateCard& a, const CandidateCard& b)
{
    if(a.score != b.score)
        return a.score > b.score;
    if(a.name != b.name)
        return a.name < b.name;
    return a.code < b.code;
}
}

const char* relation_strength_name(RelationStrength strength) noexcept
{
    switch(strength) {
    case RelationStrength::Strong: return "STRONG";
    case RelationStrength::Medium: return "MEDIUM";
    case RelationStrength::Weak: return "WEAK";
    }
    return "UNKNOWN";
}

CandidatePool CardGraphBuilder::build(const CardDatabase& database,
                                      const std::vector<uint32_t>& required,
                                      const CandidatePoolConfig& config,
                                      const std::set<uint32_t>* allowed_codes) const
{
    if(required.empty())
        throw std::invalid_argument("candidate pool requires at least one required card");
    if(config.total_limit < required.size())
        throw std::invalid_argument("total candidate limit is smaller than required card count");

    std::vector<uint32_t> unique_required;
    std::set<uint32_t> seen_required;
    for(const uint32_t code : required) {
        if(code == 0 || !database.find(code))
            throw std::invalid_argument("required card is missing from DB: " + std::to_string(code));
        if(allowed_codes && !allowed_codes->count(code))
            throw std::invalid_argument("required card is excluded by allowed candidate set: " + std::to_string(code));
        if(seen_required.insert(code).second)
            unique_required.push_back(code);
    }

    std::map<uint32_t, CardAnalysis> analyses;
    for(const auto& entry : database.records()) {
        if(allowed_codes && !allowed_codes->count(entry.first)) continue;
        analyses.emplace(entry.first, analyzer_.analyze(entry.second));
    }

    std::vector<CandidateCard> engine;
    std::vector<CandidateCard> generic;
    CandidatePool result;
    result.required = unique_required;

    for(const uint32_t code : unique_required) {
        const auto& record = *database.find(code);
        const auto& analysis = analyses.at(code);
        CandidateCard candidate;
        candidate.code = code;
        candidate.name = record.name;
        candidate.pool = "REQUIRED";
        candidate.score = 1000000;
        candidate.features = feature_list(analysis);
        candidate.relations.push_back({code, RelationStrength::Strong, "REQUIRED_SELF", "user-required card", 1000000});
        result.cards.push_back(std::move(candidate));
    }

    for(const auto& entry : database.records()) {
        const uint32_t code = entry.first;
        if(seen_required.count(code))
            continue;
        if(allowed_codes && !allowed_codes->count(code))
            continue;
        const CardRecord& card = entry.second;
        const CardAnalysis& analysis = analyses.at(code);
        CandidateCard candidate;
        candidate.code = code;
        candidate.name = card.name;
        candidate.pool = "ENGINE";
        candidate.features = feature_list(analysis);

        bool has_strong_or_medium = false;
        for(const uint32_t required_code : unique_required) {
            const CardRecord& req = *database.find(required_code);
            const CardAnalysis& req_analysis = analyses.at(required_code);

            if((card.data.alias && card.data.alias == required_code) ||
               (req.data.alias && req.data.alias == code) ||
               (card.data.alias && req.data.alias && card.data.alias == req.data.alias)) {
                add_relation(candidate, required_code, RelationStrength::Strong, "ALIAS",
                             "database alias relationship", config.strong_weight);
                has_strong_or_medium = true;
            }
            if(contains_name(card, req)) {
                add_relation(candidate, required_code, RelationStrength::Strong, "MENTIONS_REQUIRED_NAME",
                             "candidate text names required card", config.strong_weight);
                has_strong_or_medium = true;
            }
            if(contains_name(req, card)) {
                add_relation(candidate, required_code, RelationStrength::Strong, "NAMED_BY_REQUIRED",
                             "required card text names candidate", config.strong_weight);
                has_strong_or_medium = true;
            }

            uint16_t shared_set = 0;
            if(setcode_overlap(card, req, &shared_set)) {
                add_relation(candidate, required_code, RelationStrength::Medium, "SHARED_SETCODE",
                             "setcode=" + std::to_string(shared_set), config.medium_weight);
                has_strong_or_medium = true;
            }
            if(same_monster_stat(card.data.type, req.data.type, card.data.attribute, req.data.attribute)) {
                add_relation(candidate, required_code, RelationStrength::Medium, "SAME_ATTRIBUTE",
                             "attribute=" + std::to_string(card.data.attribute), config.medium_weight);
                has_strong_or_medium = true;
            }
            if(same_monster_stat(card.data.type, req.data.type, card.data.race, req.data.race)) {
                add_relation(candidate, required_code, RelationStrength::Medium, "SAME_RACE",
                             "race=" + std::to_string(card.data.race), config.medium_weight);
                has_strong_or_medium = true;
            }
            if((card.data.type & TYPE_MONSTER) && (req.data.type & TYPE_MONSTER) &&
               card.data.level != 0 && card.data.level == req.data.level) {
                add_relation(candidate, required_code, RelationStrength::Medium, "SAME_LEVEL",
                             "level=" + std::to_string(card.data.level), config.medium_weight);
                has_strong_or_medium = true;
            }
            const uint32_t card_summon = summon_mask(card.data.type);
            const uint32_t req_summon = summon_mask(req.data.type);
            if(card_summon && req_summon && (card_summon & req_summon)) {
                add_relation(candidate, required_code, RelationStrength::Medium, "SAME_SUMMON_MECHANIC",
                             "type-mask=" + std::to_string(card_summon & req_summon), config.medium_weight);
                has_strong_or_medium = true;
            }

            const size_t overlap = feature_overlap(analysis, req_analysis);
            if(overlap) {
                add_relation(candidate, required_code, RelationStrength::Weak, "FEATURE_OVERLAP",
                             "shared-features=" + std::to_string(overlap),
                             config.weak_weight * static_cast<int>(overlap));
            }
            if(broad_type(card.data.type) && broad_type(card.data.type) == broad_type(req.data.type))
                add_relation(candidate, required_code, RelationStrength::Weak, "SAME_BROAD_TYPE",
                             "monster/spell/trap class", config.weak_weight);
        }

        // Engine Pool은 최소 하나의 강/중 관계가 있어야 한다. 약한 유사도만으로 전체 카드풀이
        // 엔진 후보로 범람하지 않게 하고, WEAK 근거는 이미 연결된 후보의 정렬 보조로만 사용한다.
        if(has_strong_or_medium)
            engine.push_back(candidate);

        // Generic Pool은 강/중 관계가 없어도 범용 기능이 있는 카드를 잃지 않기 위한 별도 경로다.
        if(!has_strong_or_medium) {
            const int utility = generic_utility_score(analysis);
            if(utility > 0) {
                CandidateCard generic_card;
                generic_card.code = code;
                generic_card.name = card.name;
                generic_card.pool = "GENERIC";
                generic_card.score = utility;
                generic_card.features = feature_list(analysis);
                generic_card.relations.push_back({0, RelationStrength::Weak, "GENERIC_UTILITY",
                                                  "utility-feature-count=" + std::to_string(utility / 10), utility});
                generic.push_back(std::move(generic_card));
            }
        }
    }

    std::sort(engine.begin(), engine.end(), better);
    std::sort(generic.begin(), generic.end(), better);
    if(engine.size() > config.engine_limit)
        engine.resize(config.engine_limit);
    if(generic.size() > config.generic_limit)
        generic.resize(config.generic_limit);

    std::set<uint32_t> included(seen_required.begin(), seen_required.end());
    auto append = [&](const std::vector<CandidateCard>& source) {
        for(const auto& card : source) {
            if(result.cards.size() >= config.total_limit)
                break;
            if(included.insert(card.code).second)
                result.cards.push_back(card);
        }
    };
    append(engine);
    append(generic);
    return result;
}
}
