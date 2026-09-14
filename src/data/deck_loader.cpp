#include "deck_loader.h"
#include "ocgapi_constants.h"
#include <algorithm>
#include <charconv>
#include <fstream>
#include <stdexcept>

namespace yda {
namespace {
std::string trim(const std::string& input)
{
    const auto first = input.find_first_not_of(" \t\r\n");
    if(first == std::string::npos)
        return {};
    return input.substr(first, input.find_last_not_of(" \t\r\n") - first + 1);
}
constexpr uint32_t extra_types = TYPE_FUSION | TYPE_SYNCHRO | TYPE_XYZ | TYPE_LINK;
}

Deck parse_ydk(std::istream& input)
{
    Deck deck;
    int section = 0;
    size_t line_number = 0;
    std::string line;
    while(std::getline(input, line)) {
        ++line_number;
        if(line.size() > 4096)
            throw std::runtime_error("YDK: line too long");
        if(line_number == 1 && line.compare(0, 3, "\xef\xbb\xbf") == 0)
            line.erase(0, 3);
        line = trim(line);
        if(line.empty())
            continue;
        int next = 0;
        if(line == "#main") next = 1;
        else if(line == "#extra") next = 2;
        else if(line == "!side") next = 3;
        if(next != 0) {
            if(next <= section || (section == 0 && next != 1))
                throw std::runtime_error("YDK: repeated or out-of-order section");
            section = next;
            continue;
        }
        if(line[0] == '#')
            continue;
        if(section == 0)
            throw std::runtime_error("YDK: card before #main");
        uint32_t code = 0;
        const auto parsed = std::from_chars(line.data(), line.data() + line.size(), code);
        if(parsed.ec != std::errc() || parsed.ptr != line.data() + line.size() || code == 0)
            throw std::runtime_error("YDK: invalid card id at line " + std::to_string(line_number));
        auto& target = section == 1 ? deck.main : section == 2 ? deck.extra : deck.side;
        const size_t maximum = section == 1 ? 60 : 15;
        if(target.size() >= maximum)
            throw std::runtime_error("YDK: section exceeds maximum size");
        target.push_back(code);
    }
    if(input.bad())
        throw std::runtime_error("YDK: I/O error");
    if(section == 0)
        throw std::runtime_error("YDK: missing #main");
    return deck;
}

Deck load_ydk(const std::filesystem::path& path)
{
    std::ifstream input(path, std::ios::binary);
    if(!input)
        throw std::runtime_error("YDK open failed: " + path.string());
    return parse_ydk(input);
}

void validate_deck(const Deck& deck, const CardDatabase& db, const RequiredMain& required)
{
    if(deck.main.size() < 40 || deck.main.size() > 60)
        throw std::runtime_error("Deck: Main must contain 40..60 cards");
    if(deck.extra.size() > 15 || deck.side.size() > 15)
        throw std::runtime_error("Deck: Extra/Side must contain 0..15 cards");
    std::map<uint32_t, unsigned> copies;
    const std::vector<uint32_t>* sections[] = {&deck.main, &deck.extra, &deck.side};
    for(unsigned section = 0; section < 3; ++section) {
        for(uint32_t code : *sections[section]) {
            const auto* record = db.find(code);
            if(!record)
                throw std::runtime_error("Deck: unknown card " + std::to_string(code));
            const uint32_t type = record->data.type;
            if((record->scope & 3u) == 0 || (type & TYPE_TOKEN) != 0 ||
               (type & (TYPE_MONSTER | TYPE_SPELL | TYPE_TRAP)) == 0)
                throw std::runtime_error("Deck: non-OCG/TCG or non-deck card " + std::to_string(code));
            const bool is_extra = (type & extra_types) != 0;
            if((section == 0 && is_extra) || (section == 1 && !is_extra))
                throw std::runtime_error("Deck: wrong Main/Extra section for " + std::to_string(code));
            const uint32_t key = record->data.alias ? record->data.alias : code;
            if(++copies[key] > 3)
                throw std::runtime_error("Deck: more than 3 copies including aliases and Side: " +
                                         std::to_string(key));
        }
    }
    for(const auto& entry : required) {
        if(entry.second == 0 || entry.second > 3 || !db.find(entry.first))
            throw std::runtime_error("Deck: invalid required Main card setting");
        const auto count = std::count(deck.main.begin(), deck.main.end(), entry.first);
        if(static_cast<unsigned>(count) < entry.second)
            throw std::runtime_error("Deck: required Main card missing: " + std::to_string(entry.first));
    }
}
}
