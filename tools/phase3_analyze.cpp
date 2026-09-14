#include "analysis/card_graph.h"
#include "data/card_database.h"
#include <charconv>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
uint32_t parse_u32(const std::string& text, const char* field)
{
    uint32_t value = 0;
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    if(result.ec != std::errc() || result.ptr != text.data() + text.size() || value == 0)
        throw std::invalid_argument(std::string("invalid ") + field + ": " + text);
    return value;
}

size_t parse_size(const std::string& text, const char* field)
{
    uint64_t value = 0;
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    if(result.ec != std::errc() || result.ptr != text.data() + text.size() || value == 0 || value > 10000)
        throw std::invalid_argument(std::string("invalid ") + field + ": " + text);
    return static_cast<size_t>(value);
}

std::string escape_json(const std::string& input)
{
    static const char hex[] = "0123456789abcdef";
    std::string out;
    for(unsigned char ch : input) {
        switch(ch) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\b': out += "\\b"; break;
        case '\f': out += "\\f"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if(ch < 0x20) {
                out += "\\u00";
                out.push_back(hex[(ch >> 4) & 0xf]);
                out.push_back(hex[ch & 0xf]);
            } else {
                out.push_back(static_cast<char>(ch));
            }
        }
    }
    return out;
}

void write_json(std::ostream& out, const yda::CandidatePool& pool,
                const yda::CandidatePoolConfig& config)
{
    out << "{\n  \"schema\": 1,\n  \"analysis_profile\": \"phase3-text-metadata-v1\",\n";
    out << "  \"required\": [";
    for(size_t i = 0; i < pool.required.size(); ++i) {
        if(i) out << ", ";
        out << pool.required[i];
    }
    out << "],\n  \"config\": {\"engine_limit\": " << config.engine_limit
        << ", \"generic_limit\": " << config.generic_limit
        << ", \"total_limit\": " << config.total_limit
        << ", \"strong_weight\": " << config.strong_weight
        << ", \"medium_weight\": " << config.medium_weight
        << ", \"weak_weight\": " << config.weak_weight << "},\n";
    out << "  \"candidates\": [\n";
    for(size_t i = 0; i < pool.cards.size(); ++i) {
        const auto& card = pool.cards[i];
        out << "    {\"code\": " << card.code << ", \"name\": \"" << escape_json(card.name)
            << "\", \"pool\": \"" << card.pool << "\", \"score\": " << card.score << ", \"features\": [";
        for(size_t j = 0; j < card.features.size(); ++j) {
            if(j) out << ", ";
            out << "\"" << yda::feature_name(card.features[j]) << "\"";
        }
        out << "], \"relations\": [";
        for(size_t j = 0; j < card.relations.size(); ++j) {
            if(j) out << ", ";
            const auto& relation = card.relations[j];
            out << "{\"required_code\": " << relation.required_code
                << ", \"strength\": \"" << yda::relation_strength_name(relation.strength)
                << "\", \"kind\": \"" << escape_json(relation.kind)
                << "\", \"detail\": \"" << escape_json(relation.detail)
                << "\", \"score\": " << relation.score << "}";
        }
        out << "]}" << (i + 1 == pool.cards.size() ? "\n" : ",\n");
    }
    out << "  ]\n}\n";
}
}

int main(int argc, char** argv)
{
    try {
        std::filesystem::path db_path;
        std::filesystem::path output_path;
        std::vector<uint32_t> required;
        yda::CandidatePoolConfig config;
        for(int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            auto value = [&]() -> std::string {
                if(++i >= argc)
                    throw std::invalid_argument("missing value for " + arg);
                return argv[i];
            };
            if(arg == "--db") db_path = value();
            else if(arg == "--required") required.push_back(parse_u32(value(), "required card"));
            else if(arg == "--engine-limit") config.engine_limit = parse_size(value(), "engine limit");
            else if(arg == "--generic-limit") config.generic_limit = parse_size(value(), "generic limit");
            else if(arg == "--total-limit") config.total_limit = parse_size(value(), "total limit");
            else if(arg == "--output") output_path = value();
            else throw std::invalid_argument("unknown argument: " + arg);
        }
        if(db_path.empty())
            throw std::invalid_argument("--db is required");
        if(required.empty())
            throw std::invalid_argument("at least one --required is required");
        if(output_path.empty())
            throw std::invalid_argument("--output is required");

        yda::CardDatabase database(db_path);
        yda::CardGraphBuilder graph;
        const auto pool = graph.build(database, required, config);
        const auto parent = output_path.parent_path();
        if(!parent.empty())
            std::filesystem::create_directories(parent);
        std::ofstream output(output_path, std::ios::binary | std::ios::trunc);
        if(!output)
            throw std::runtime_error("cannot open output: " + output_path.string());
        write_json(output, pool, config);
        output.close();
        if(!output)
            throw std::runtime_error("failed to write output: " + output_path.string());
        size_t engine = 0, generic = 0;
        for(const auto& card : pool.cards) {
            if(card.pool == "ENGINE") ++engine;
            if(card.pool == "GENERIC") ++generic;
        }
        std::cout << "PHASE3 ANALYSIS PASS: required=" << pool.required.size()
                  << " candidates=" << pool.cards.size()
                  << " engine=" << engine << " generic=" << generic << '\n';
        return 0;
    } catch(const std::exception& error) {
        std::cerr << "PHASE3 ANALYSIS FAIL: " << error.what() << '\n';
        return 2;
    }
}
