#include "analysis/card_analyzer.h"
#include "analysis/card_graph.h"
#include "data/card_database.h"
#include "ocgapi_constants.h"
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sqlite3.h>

namespace {
int checks = 0;

void check(bool condition, const char* message)
{
    ++checks;
    if(!condition)
        throw std::runtime_error(message);
}

void exec(sqlite3* db, const char* sql)
{
    char* error = nullptr;
    if(sqlite3_exec(db, sql, nullptr, nullptr, &error) != SQLITE_OK) {
        const std::string message = error ? error : "sqlite error";
        sqlite3_free(error);
        throw std::runtime_error(message);
    }
}

void create_fixture(const std::filesystem::path& path)
{
    std::filesystem::remove(path);
    sqlite3* db = nullptr;
    if(sqlite3_open(path.string().c_str(), &db) != SQLITE_OK)
        throw std::runtime_error("cannot create fixture db");
    try {
        exec(db, "CREATE TABLE datas(id INTEGER PRIMARY KEY, ot INTEGER, alias INTEGER, setcode INTEGER, type INTEGER, atk INTEGER, def INTEGER, level INTEGER, race INTEGER, attribute INTEGER, category INTEGER)");
        exec(db, "CREATE TABLE texts(id INTEGER PRIMARY KEY, name TEXT, desc TEXT)");
        exec(db, "INSERT INTO datas VALUES"
                 "(100,3,0,4660,33,2500,2000,8,1,16,0),"
                 "(101,3,0,4660,33,1000,1000,4,1,16,0),"
                 "(102,3,0,4660,33,1500,1500,4,2,16,0),"
                 "(103,3,0,0,2,0,0,0,0,0,0),"
                 "(104,3,0,0,33,2000,1000,8,1,16,0),"
                 "(105,3,0,0,2,0,0,0,0,0,0),"
                 "(106,3,100,0,33,2500,2000,8,1,16,0)");
        exec(db, "INSERT INTO texts VALUES"
                 "(100,'Alpha Dragon','A legendary monster.'),"
                 "(101,'Alpha Searcher','If this card is Normal Summoned: Add 1 \\\"Alpha Dragon\\\" from your Deck to your hand.'),"
                 "(102,'Alpha Shield','If this card is Special Summoned, it cannot be destroyed by card effects.'),"
                 "(103,'Universal Answer','When your opponent activates a card: negate the activation, and if you do, destroy it.'),"
                 "(104,'Other Dragon','A different dragon.'),"
                 "(105,'Blank Spell','Nothing relevant happens.'),"
                 "(106,'Alpha Alternate','This card is always treated as Alpha Dragon.')");
        sqlite3_close(db);
    } catch(...) {
        sqlite3_close(db);
        throw;
    }
}

const yda::CandidateCard* find(const yda::CandidatePool& pool, uint32_t code)
{
    for(const auto& card : pool.cards)
        if(card.code == code)
            return &card;
    return nullptr;
}

bool relation(const yda::CandidateCard& card, const std::string& kind, yda::RelationStrength strength)
{
    for(const auto& item : card.relations)
        if(item.kind == kind && item.strength == strength)
            return true;
    return false;
}
}

int main()
{
    try {
        const auto path = std::filesystem::temp_directory_path() / "yda_phase3_unit.cdb";
        create_fixture(path);
        yda::CardDatabase database(path);
        check(database.size() == 7, "fixture DB record count");

        yda::CardAnalyzer analyzer;
        const auto searcher = analyzer.analyze(*database.find(101));
        check(yda::CardAnalyzer::has_feature(searcher, yda::CardFeature::Search), "SEARCH detected");
        check(yda::CardAnalyzer::has_feature(searcher, yda::CardFeature::NormalSummon), "NORMAL_SUMMON detected");
        check(yda::CardAnalyzer::has_feature(searcher, yda::CardFeature::Trigger), "TRIGGER detected");
        check(!searcher.conditions.empty(), "conditions recorded");
        check(!searcher.zones.empty(), "zones recorded");

        const auto generic = analyzer.analyze(*database.find(103));
        check(yda::CardAnalyzer::has_feature(generic, yda::CardFeature::Negate), "NEGATE detected");
        check(yda::CardAnalyzer::has_feature(generic, yda::CardFeature::Destroy), "DESTROY detected");
        check(yda::CardAnalyzer::has_feature(generic, yda::CardFeature::Trigger), "generic TRIGGER detected");

        yda::CandidatePoolConfig config;
        config.engine_limit = 10;
        config.generic_limit = 10;
        config.total_limit = 20;
        yda::CardGraphBuilder graph;
        const auto pool = graph.build(database, {100}, config);
        check(pool.required.size() == 1 && pool.required[0] == 100, "required preserved");
        check(!pool.cards.empty() && pool.cards.front().code == 100, "required first");
        check(pool.cards.front().pool == "REQUIRED", "required pool tag");

        const auto* c101 = find(pool, 101);
        check(c101 != nullptr, "direct name candidate included");
        check(relation(*c101, "MENTIONS_REQUIRED_NAME", yda::RelationStrength::Strong), "strong name relation");
        check(relation(*c101, "SHARED_SETCODE", yda::RelationStrength::Medium), "setcode relation");
        check(c101->score >= config.strong_weight + config.medium_weight, "relation score accumulated");

        const auto* c104 = find(pool, 104);
        check(c104 != nullptr, "metadata relation candidate included");
        check(relation(*c104, "SAME_ATTRIBUTE", yda::RelationStrength::Medium), "attribute relation");
        check(relation(*c104, "SAME_RACE", yda::RelationStrength::Medium), "race relation");
        check(relation(*c104, "SAME_LEVEL", yda::RelationStrength::Medium), "level relation");

        const auto* c106 = find(pool, 106);
        check(c106 != nullptr, "alias candidate included");
        check(relation(*c106, "ALIAS", yda::RelationStrength::Strong), "alias relation strong");

        const auto* c103 = find(pool, 103);
        check(c103 != nullptr, "generic utility retained");
        check(c103->pool == "GENERIC", "generic pool tag");
        check(relation(*c103, "GENERIC_UTILITY", yda::RelationStrength::Weak), "generic reason recorded");
        check(find(pool, 105) == nullptr, "unrelated blank card excluded");

        const auto again = graph.build(database, {100}, config);
        check(pool.cards.size() == again.cards.size(), "deterministic candidate count");
        for(size_t i = 0; i < pool.cards.size(); ++i) {
            check(pool.cards[i].code == again.cards[i].code, "deterministic order");
            check(pool.cards[i].score == again.cards[i].score, "deterministic score");
        }

        bool missing_rejected = false;
        try { (void)graph.build(database, {999999}, config); }
        catch(const std::invalid_argument&) { missing_rejected = true; }
        check(missing_rejected, "missing required rejected");

        bool limit_rejected = false;
        auto tiny = config;
        tiny.total_limit = 1;
        try { (void)graph.build(database, {100, 101}, tiny); }
        catch(const std::invalid_argument&) { limit_rejected = true; }
        check(limit_rejected, "too-small total limit rejected");

        std::filesystem::remove(path);
        std::cout << "PHASE3 UNIT PASS: " << checks << " checks\n";
        return 0;
    } catch(const std::exception& error) {
        std::cerr << "PHASE3 UNIT FAIL after " << checks << " checks: " << error.what() << '\n';
        return 1;
    }
}
