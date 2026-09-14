#include "card_analyzer.h"
#include <algorithm>
#include <cctype>
#include <initializer_list>
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

bool contains(std::string_view haystack, std::string_view needle)
{
    return !needle.empty() && haystack.find(needle) != std::string_view::npos;
}

bool contains_any(std::string_view text, std::initializer_list<std::string_view> patterns,
                  std::string* hit = nullptr)
{
    for(const auto pattern : patterns) {
        if(contains(text, pattern)) {
            if(hit)
                *hit = std::string(pattern);
            return true;
        }
    }
    return false;
}

void add_feature(CardAnalysis& out, CardFeature feature, std::string evidence)
{
    for(const auto& item : out.features)
        if(item.feature == feature)
            return;
    out.features.push_back({feature, std::move(evidence)});
}

void add_if(CardAnalysis& out, CardFeature feature, std::string_view text,
            std::initializer_list<std::string_view> patterns)
{
    std::string hit;
    if(contains_any(text, patterns, &hit))
        add_feature(out, feature, std::move(hit));
}

void add_marker(std::vector<std::string>& out, std::string_view text,
                std::string_view label, std::initializer_list<std::string_view> patterns)
{
    if(std::find(out.begin(), out.end(), label) != out.end())
        return;
    if(contains_any(text, patterns))
        out.emplace_back(label);
}
}

const char* feature_name(CardFeature feature) noexcept
{
    switch(feature) {
    case CardFeature::Search: return "SEARCH";
    case CardFeature::Draw: return "DRAW";
    case CardFeature::SpecialSummon: return "SPECIAL_SUMMON";
    case CardFeature::NormalSummon: return "NORMAL_SUMMON";
    case CardFeature::Negate: return "NEGATE";
    case CardFeature::Destroy: return "DESTROY";
    case CardFeature::Banish: return "BANISH";
    case CardFeature::Return: return "RETURN";
    case CardFeature::SendToGY: return "SEND_TO_GY";
    case CardFeature::Recover: return "RECOVER";
    case CardFeature::Material: return "MATERIAL";
    case CardFeature::Token: return "TOKEN";
    case CardFeature::Protection: return "PROTECTION";
    case CardFeature::Discard: return "DISCARD";
    case CardFeature::Trigger: return "TRIGGER";
    case CardFeature::Target: return "TARGET";
    }
    return "UNKNOWN";
}

CardAnalysis CardAnalyzer::analyze(const CardRecord& card) const
{
    CardAnalysis out;
    out.code = card.data.code;
    out.name = card.name;
    const std::string text = lower_ascii(card.text);

    // BabelCDB의 영문 효과 텍스트를 대상으로 하는 1차 구조화 규칙이다.
    // 해당 문구가 실제로 존재할 때만 feature를 부여하여 추론 근거를 보존한다.
    add_if(out, CardFeature::Search, text,
           {"from your deck to your hand", "search your deck", "add 1 card from your deck"});
    add_if(out, CardFeature::Draw, text, {"draw 1 card", "draw 2 cards", "draw cards", "draw 1"});
    add_if(out, CardFeature::SpecialSummon, text, {"special summon"});
    add_if(out, CardFeature::NormalSummon, text, {"normal summon", "normal summoned", "normal set"});
    add_if(out, CardFeature::Negate, text, {"negate"});
    add_if(out, CardFeature::Destroy, text, {"destroy"});
    add_if(out, CardFeature::Banish, text, {"banish"});
    add_if(out, CardFeature::Return, text,
           {"return it to the hand", "return that target to the hand", "return them to the hand",
            "return it to the deck", "return that target to the deck", "shuffle it into the deck",
            "shuffle them into the deck"});
    add_if(out, CardFeature::SendToGY, text,
           {"send it to the gy", "send that target to the gy", "send them to the gy",
            "send 1 card to the gy", "send 1 monster to the gy", "send to the gy",
            "send it to the graveyard", "send to the graveyard"});
    if((contains(text, "from your gy") || contains(text, "from your graveyard")) &&
       contains(text, "to your hand"))
        add_feature(out, CardFeature::Recover, "from GY to hand");
    add_if(out, CardFeature::Material, text,
           {"fusion material", "synchro material", "xyz material", "link material", "as material", "materials"});
    add_if(out, CardFeature::Token, text, {"token"});
    add_if(out, CardFeature::Protection, text,
           {"cannot be destroyed", "unaffected by", "cannot be targeted", "cannot target this card"});
    add_if(out, CardFeature::Discard, text, {"discard"});
    add_if(out, CardFeature::Trigger, text,
           {"when this card", "if this card", "if you", "when you", "during your", "during the"});
    add_if(out, CardFeature::Target, text, {"target 1", "target 2", "target that", "target those"});

    add_marker(out.conditions, text, "IF", {"if "});
    add_marker(out.conditions, text, "WHEN", {"when "});
    add_marker(out.conditions, text, "WHILE", {"while "});
    add_marker(out.conditions, text, "DURING", {"during "});

    add_marker(out.costs, text, "PAY_LP", {"pay 500 lp", "pay 1000 lp", "pay 2000 lp", "pay half your lp"});
    add_marker(out.costs, text, "DISCARD", {"discard 1", "discard this card", "discard 2"});
    add_marker(out.costs, text, "TRIBUTE", {"tribute 1", "tribute this card", "tribute 2"});
    add_marker(out.costs, text, "BANISH", {"banish 1", "banish this card", "banish 2"});
    add_marker(out.costs, text, "SEND_TO_GY", {"send this card to the gy", "send 1 card from your hand to the gy"});

    add_marker(out.zones, text, "HAND", {"hand"});
    add_marker(out.zones, text, "DECK", {"deck"});
    add_marker(out.zones, text, "GY", {" gy", "graveyard"});
    add_marker(out.zones, text, "BANISHED", {"banished", "banish"});
    add_marker(out.zones, text, "FIELD", {"field"});
    add_marker(out.zones, text, "EXTRA_DECK", {"extra deck"});
    add_marker(out.zones, text, "MONSTER_ZONE", {"monster zone"});
    add_marker(out.zones, text, "SPELL_TRAP_ZONE", {"spell & trap zone", "spell/trap zone"});

    return out;
}

bool CardAnalyzer::has_feature(const CardAnalysis& analysis, CardFeature feature) noexcept
{
    return std::any_of(analysis.features.begin(), analysis.features.end(),
                       [feature](const FeatureEvidence& item) { return item.feature == feature; });
}
}
