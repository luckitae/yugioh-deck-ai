#include "data/card_database.h"
#include "data/deck_loader.h"
#include "data/script_loader.h"
#include "protocol/smoke_response.h"
#include "ocgapi.h"
#include "ocgapi_constants.h"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <sqlite3.h>

// 이 파일만의 OCG_LoadScript 테스트 대역이다. 실제 Lua 실행 검증이 아니다.
// phase2_smoke에는 이 파일을 링크하지 않고 진짜 -locgcore를 링크한다.
static unsigned mock_loads = 0;
static yda::ScriptLoader* recursive_loader = nullptr;
extern "C" int OCG_LoadScript(OCG_Duel duel, const char* bytes, uint32_t length, const char* name)
{
    ++mock_loads;
    if(std::string(name) == "parent.lua" && recursive_loader)
        return yda::ScriptLoader::read(recursive_loader, duel, "child.lua");
    return length > 0 && bytes[0] != '!';
}

namespace {
unsigned checks = 0;
void check(bool value, const std::string& name)
{
    ++checks;
    if(!value)
        throw std::runtime_error("FAIL: " + name);
}
template<class F> void rejects(F&& action, const std::string& name)
{
    bool rejected = false;
    try { action(); } catch(const std::exception&) { rejected = true; }
    check(rejected, name);
}
struct Temporary {
    std::filesystem::path path;
    Temporary()
    {
        path = std::filesystem::temp_directory_path() /
               ("yda-phase2-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        if(!std::filesystem::create_directory(path))
            throw std::runtime_error("temp directory failed");
    }
    ~Temporary() { std::error_code error; std::filesystem::remove_all(path, error); }
};
void sql(sqlite3* db, const char* command)
{
    if(sqlite3_exec(db, command, nullptr, nullptr, nullptr) != SQLITE_OK)
        throw std::runtime_error(sqlite3_errmsg(db));
}
void insert(sqlite3* db, uint32_t id, uint32_t type = TYPE_MONSTER | TYPE_NORMAL,
            uint32_t alias = 0, int64_t level = 4, uint64_t race = RACE_WARRIOR,
            int32_t defense = 1000, uint64_t sets = 0, uint32_t scope = 3)
{
    sqlite3_stmt* stmt = nullptr;
    if(sqlite3_prepare_v2(db, "INSERT INTO datas VALUES(?,?,?,?,?,?,?,?,?,?,?)", -1, &stmt, nullptr) != SQLITE_OK)
        throw std::runtime_error("insert prepare failed");
    int64_t values[] = {id, alias, static_cast<int64_t>(sets), type, -2, defense, level,
                        static_cast<int64_t>(race), ATTRIBUTE_LIGHT, scope, 0};
    for(int i = 0; i < 11; ++i)
        sqlite3_bind_int64(stmt, i + 1, values[i]);
    const int result = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    if(result != SQLITE_DONE)
        throw std::runtime_error("insert failed");
    const std::string text = "INSERT INTO texts VALUES(" + std::to_string(id) + ",'unit card','unit text')";
    sql(db, text.c_str());
}
void create_database(const std::filesystem::path& path)
{
    sqlite3* db = nullptr;
    if(sqlite3_open(path.string().c_str(), &db) != SQLITE_OK)
        throw std::runtime_error("unit DB creation failed");
    sql(db, "CREATE TABLE datas(id INTEGER,alias INTEGER,setcode INTEGER,type INTEGER,atk INTEGER,def INTEGER,level INTEGER,race INTEGER,attribute INTEGER,ot INTEGER,category INTEGER)");
    sql(db, "CREATE TABLE texts(id INTEGER PRIMARY KEY,name TEXT,desc TEXT)");
    for(uint32_t i = 1000; i < 1030; ++i)
        insert(db, i);
    insert(db, 2000, TYPE_MONSTER | TYPE_LINK, 0, 3, uint64_t(1) << 40, 0x141, 0xabcd000012340001ULL);
    insert(db, 2001, TYPE_MONSTER | TYPE_NORMAL | TYPE_PENDULUM, 0, (8u << 24) | (1u << 16) | 7);
    insert(db, 2002, TYPE_MONSTER | TYPE_NORMAL, 1000);
    insert(db, 2003, TYPE_MONSTER | TYPE_TOKEN);
    insert(db, 2004, TYPE_MONSTER | TYPE_NORMAL, 0, 4, 1, 0, 0, 8);
    insert(db, 2005, TYPE_MONSTER | TYPE_EFFECT, 0, -254);
    insert(db, yda::hinotama_code, TYPE_SPELL);
    sqlite3_close(db);
}
yda::Deck normal(unsigned size)
{
    yda::Deck deck;
    for(unsigned i = 0; i < size; ++i)
        deck.main.push_back(1000 + i / 3);
    return deck;
}
std::vector<uint8_t> idle(bool end, bool activate = false)
{
    std::vector<uint8_t> p{MSG_SELECT_IDLECMD, 0};
    for(unsigned i = 0; i < 5; ++i) yda::append_u32(p, 0);
    yda::append_u32(p, activate ? 1 : 0);
    if(activate) {
        yda::append_u32(p, yda::hinotama_code);
        p.push_back(0); p.push_back(LOCATION_HAND);
        yda::append_u32(p, 0);
        yda::append_u32(p, 0); yda::append_u32(p, 0);
        p.push_back(0);
    }
    p.push_back(0); p.push_back(end); p.push_back(0);
    return p;
}
yda::Response respond(const std::vector<uint8_t>& p, yda::SmokePolicy policy = yda::SmokePolicy::Pass)
{
    DecodedMessage message{};
    message.type = p.empty() ? 0 : p[0]; message.payload = p.data();
    message.payload_size = static_cast<uint32_t>(p.size());
    return yda::smoke_response(message, policy);
}
void write(const std::filesystem::path& path, const std::string& value)
{
    std::ofstream file(path); file << value;
    if(!file) throw std::runtime_error("unit write failed");
}

void tests(const Temporary& temp)
{
    const auto dbpath = temp.path / "unit.cdb";
    create_database(dbpath);
    yda::CardDatabase db(dbpath);
    check(db.size() == 37, "all database records loaded");
    check(db.find(999999) == nullptr, "unknown record");
    const auto* link = db.find(2000);
    check(link->data.race == (uint64_t(1) << 40), "64-bit race preserved");
    check(link->data.defense == 0 && link->data.link_marker == 0x141, "Link DEF mapping");
    check(link->data.attack == -2, "negative ATK preserved");
    check(link->setcodes == std::array<uint16_t, 5>{1,0x1234,0xabcd,0,0}, "setcodes packed/zero terminator");
    const auto* pendulum = db.find(2001);
    check(pendulum->data.level == 7 && pendulum->data.lscale == 8 && pendulum->data.rscale == 1,
          "Pendulum level/scales");
    check(db.find(2005)->data.level == static_cast<uint32_t>(-2), "negative encoded level");
    yda::CardReaderContext reader{db};
    OCG_CardData out{};
    yda::CardReaderContext::read(&reader, 2000, &out);
    auto* saved = out.setcodes;
    check(out.code == 2000 && saved[2] == 0xabcd, "ABI callback");
    yda::CardReaderContext::release(&reader, &out);
    for(uint32_t i = 1000; i < 1030; ++i)
        yda::CardReaderContext::read(&reader, i, &out);
    check(saved[2] == 0xabcd && reader.done == 1, "setcode lifetime");
    yda::CardReaderContext::read(&reader, 999999, &out);
    check(reader.failed && reader.missing_code == 999999 && out.code == 0, "missing card failure");
    rejects([&] { yda::CardDatabase absent(temp.path / "missing.cdb"); }, "missing DB");
    check(!std::filesystem::exists(temp.path / "missing.cdb"), "read-only DB does not create missing file");
    write(temp.path / "garbage.cdb", "not sqlite");
    rejects([&] { yda::CardDatabase garbage(temp.path / "garbage.cdb"); }, "corrupt DB");
    for(unsigned size : {40, 41, 50, 59, 60}) {
        yda::validate_deck(normal(size), db);
        check(true, "valid Main size " + std::to_string(size));
    }
    rejects([&] { yda::validate_deck(normal(39), db); }, "39 cards rejected");
    rejects([&] { yda::validate_deck(normal(61), db); }, "61 cards rejected");
    auto deck = normal(40);
    deck.main[39] = 999999;
    rejects([&] { yda::validate_deck(deck, db); }, "unknown card rejected");
    deck = normal(40); deck.main[39] = 1000;
    rejects([&] { yda::validate_deck(deck, db); }, "four copies rejected");
    deck = normal(40); deck.side = {2002};
    rejects([&] { yda::validate_deck(deck, db); }, "alias+Side copy total");
    deck = normal(40); deck.main[39] = 2000;
    rejects([&] { yda::validate_deck(deck, db); }, "Extra monster in Main rejected");
    deck = normal(40); deck.extra = {1029};
    rejects([&] { yda::validate_deck(deck, db); }, "Main monster in Extra rejected");
    deck = normal(40); deck.extra = {2000}; deck.side = {1029};
    yda::validate_deck(deck, db, {{1000,3}});
    check(true, "separate Main/Extra/Side and required card");
    rejects([&] { yda::validate_deck(deck, db, {{1029,1}}); }, "Side does not satisfy required Main");
    rejects([&] { yda::validate_deck(deck, db, {{1000,0}}); }, "zero required count rejected");
    for(uint32_t invalid : {2003u, 2004u}) {
        deck = normal(40); deck.main[39] = invalid;
        rejects([&] { yda::validate_deck(deck, db); }, "Token/non-format rejected");
    }
    deck = normal(40); deck.extra.assign(16, 2000);
    rejects([&] { yda::validate_deck(deck, db); }, "16 Extra cards rejected");
    deck = normal(40); deck.side.assign(16, 1029);
    rejects([&] { yda::validate_deck(deck, db); }, "16 Side cards rejected");
    std::stringstream valid("\xef\xbb\xbf#created by unit\r\n#main\r\n1000\r\n#extra\r\n2000\r\n!side\r\n1029\r\n");
    auto parsed = yda::parse_ydk(valid);
    check(parsed.main.size() == 1 && parsed.extra[0] == 2000 && parsed.side[0] == 1029, "BOM/CRLF/sections");
    for(const std::string& invalid : {"1000\n", "#main\n0\n", "#main\n-1\n", "#main\n4294967296\n",
                                     "#main\n1000x\n", "#main\n#main\n", "#extra\n", "#main\n!unknown\n"}) {
        rejects([&] { std::stringstream input(invalid); yda::parse_ydk(input); }, "invalid YDK syntax");
    }
    std::stringstream too_many("#main\n");
    for(int i = 0; i < 61; ++i) too_many << "1000\n";
    rejects([&] { yda::parse_ydk(too_many); }, "parser size cap");
    check(yda::read_u32(respond(idle(true)).bytes.data()) == 7, "legal End Phase");
    rejects([&] { respond(idle(false)); }, "forbidden End Phase not sent");
    auto activation = respond(idle(true, true), yda::SmokePolicy::Hinotama);
    check(yda::read_u32(activation.bytes.data()) == 5 && activation.activated_code == yda::hinotama_code,
          "real effect activation encoder");
    auto bad_idle = idle(true); bad_idle.pop_back();
    rejects([&] { respond(bad_idle); }, "truncated Idle");
    bad_idle = idle(true); bad_idle[1] = 2;
    rejects([&] { respond(bad_idle); }, "invalid player");
    bad_idle = idle(true); bad_idle.back() = 2;
    rejects([&] { respond(bad_idle); }, "invalid Idle flag");
    std::vector<uint8_t> chain{MSG_SELECT_CHAIN,0,0,0};
    yda::append_u32(chain,0); yda::append_u32(chain,0); yda::append_u32(chain,0);
    check(yda::read_u32(respond(chain).bytes.data()) == UINT32_MAX, "optional chain decline");
    chain[3] = 1;
    rejects([&] { respond(chain); }, "empty forced chain");
    chain[12] = 1; chain.resize(39,0);
    check(yda::read_u32(respond(chain).bytes.data()) == 0, "forced chain index");
    chain.pop_back();
    rejects([&] { respond(chain); }, "truncated chain candidates");
    std::vector<uint8_t> cards{MSG_SELECT_CARD,0,0};
    yda::append_u32(cards,1); yda::append_u32(cards,2); yda::append_u32(cards,2);
    cards.resize(43,0);
    auto selected = respond(cards);
    check(selected.bytes.size() == 12 && yda::read_u32(selected.bytes.data()+4) == 1 &&
          yda::read_u32(selected.bytes.data()+8) == 0, "uint32 selected-card format");
    cards.pop_back();
    rejects([&] { respond(cards); }, "truncated card candidates");
    cards.resize(43,0); cards[3] = 3;
    rejects([&] { respond(cards); }, "invalid minimum");
    std::vector<uint8_t> place{MSG_SELECT_PLACE,1,1};
    yda::append_u32(place, ~(uint32_t(1) << 8));
    auto placed = respond(place);
    check(placed.bytes == std::vector<uint8_t>{1,LOCATION_SZONE,0}, "PLACE relative controller");
    place = {MSG_SELECT_PLACE,0,1}; yda::append_u32(place, ~(uint32_t(1) << 24));
    check(respond(place).bytes == std::vector<uint8_t>{1,LOCATION_SZONE,0}, "PLACE opponent controller");
    place = {MSG_SELECT_PLACE,0,1}; yda::append_u32(place,UINT32_MAX);
    rejects([&] { respond(place); }, "no legal place");
    place = {MSG_SELECT_PLACE,0,2}; yda::append_u32(place, ~(uint32_t(3) << 8));
    check(respond(place).bytes == std::vector<uint8_t>{0,LOCATION_SZONE,0,0,LOCATION_SZONE,1}, "multiple places without duplicates");
    rejects([&] { respond({MSG_SELECT_SUM,0}); }, "unsupported selection fails closed");
    const auto payload = idle(true);
    std::vector<uint8_t> frame; yda::append_u32(frame,static_cast<uint32_t>(payload.size()));
    frame.insert(frame.end(),payload.begin(),payload.end());
    uint32_t offset = 0; DecodedMessage message{};
    check(decode_next_message(frame.data(),frame.size(),&offset,&message) && offset == frame.size(), "complete frame");
    frame.pop_back(); offset = 0;
    check(!decode_next_message(frame.data(),frame.size(),&offset,&message), "incomplete frame rejected");
    const auto root = temp.path / "scripts";
    std::filesystem::create_directories(root / "official");
    std::filesystem::create_directories(root / "unofficial");
    write(root/"constant.lua", "constants test double"); write(root/"utility.lua", "utilities test double");
    write(root/"official/c46130346.lua", "card test double");
    write(root/"unofficial/proc_unofficial.lua", "helper test double");
    write(root/"parent.lua", "parent"); write(root/"child.lua", "child");
    const auto duel = reinterpret_cast<OCG_Duel>(uintptr_t(1));
    yda::ScriptLoader scripts(root,db);
    scripts.bootstrap(duel);
    check(scripts.loaded_count() == 2, "common bootstrap (mock engine)");
    check(yda::ScriptLoader::read(&scripts,duel,"c46130346.lua") > 0, "official card path");
    check(yda::ScriptLoader::read(&scripts,duel,"c1000.lua") == 0 && !scripts.failed(), "normal card may have no script");
    check(yda::ScriptLoader::read(&scripts,duel,"c0.lua") == 0 && !scripts.failed(), "internal c0 may have no script");
    check(yda::ScriptLoader::read(&scripts,duel,"proc_unofficial.lua") > 0, "common helper fallback");
    recursive_loader = &scripts;
    check(yda::ScriptLoader::read(&scripts,duel,"parent.lua") > 0 && scripts.loaded("child.lua"), "nested callback/cache lifetime");
    recursive_loader = nullptr;
    const unsigned before = mock_loads;
    check(yda::ScriptLoader::read(&scripts,duel,"../outside.lua") == 0 && scripts.failed() && mock_loads == before, "path traversal rejected before engine call");
    yda::ScriptLoader missing(root,db);
    check(yda::ScriptLoader::read(&missing,duel,"c2001.lua") == 0 && missing.failed(), "Pendulum normal needs script");
    yda::ScriptLoader missing_effect(root,db);
    check(yda::ScriptLoader::read(&missing_effect,duel,"c2005.lua") == 0 && missing_effect.failed(), "missing effect script fails");
    write(root/"bad.lua", "!simulated syntax error");
    yda::ScriptLoader bad(root,db);
    check(yda::ScriptLoader::read(&bad,duel,"bad.lua") == 0 && bad.failed(), "engine load failure propagated");
    yda::ScriptLoader logger(root,db);
    yda::ScriptLoader::log(&logger,"expected test error",OCG_LOG_TYPE_ERROR);
    check(logger.failed() && logger.engine_errors == 1, "engine errors latched");
    write(temp.path/"outside.lua", "outside");
    std::filesystem::create_symlink(temp.path/"outside.lua",root/"escape.lua");
    yda::ScriptLoader escape(root,db);
    check(yda::ScriptLoader::read(&escape,duel,"escape.lua") == 0 && escape.failed(), "symlink escape rejected");
}
}
int main()
{
    try {
        Temporary temporary;
        tests(temporary);
        std::cout << "PHASE2 UNIT PASS: " << checks << " checks (Lua calls mocked)\n";
        return 0;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
