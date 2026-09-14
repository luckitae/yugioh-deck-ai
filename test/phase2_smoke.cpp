#include "data/card_database.h"
#include "data/deck_loader.h"
#include "data/script_loader.h"
#include "protocol/smoke_response.h"
#include "ocgapi.h"
#include "ocgapi_constants.h"
#include <array>
#include <charconv>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <stdexcept>

namespace {
struct Arguments {
    std::filesystem::path db, scripts, deck0, deck1, result;
    uint64_t seed = 1;
    yda::SmokePolicy policy = yda::SmokePolicy::Pass;
    yda::RequiredMain required;
    bool validate_only = false;
};
struct Result {
    std::string status = "input_error";
    std::string error;
    int winner = -1, reason = -1;
    uint64_t calls = 0, turns = 0, activations = 0, solved = 0, damage_events = 0;
    uint64_t damage = 0, scripts = 0, optional_scripts = 0, engine_errors = 0, card_reads = 0;
    std::array<size_t, 2> main{}, extra{}, side{};
};
struct DuelGuard {
    OCG_Duel value = nullptr;
    ~DuelGuard() { if(value) OCG_DestroyDuel(value); }
};
uint64_t number(const std::string& input)
{
    uint64_t value = 0;
    const auto parsed = std::from_chars(input.data(), input.data() + input.size(), value);
    if(parsed.ec != std::errc() || parsed.ptr != input.data() + input.size())
        throw std::runtime_error("Invalid unsigned integer: " + input);
    return value;
}
void parse(int argc, char** argv, Arguments& args)
{
    for(int i = 1; i < argc; ++i) {
        const std::string key(argv[i]);
        if(key == "--validate-only") { args.validate_only = true; continue; }
        if(++i >= argc)
            throw std::runtime_error("Missing value for " + key);
        const std::string value(argv[i]);
        if(key == "--db") args.db = value;
        else if(key == "--scripts") args.scripts = value;
        else if(key == "--deck0") args.deck0 = value;
        else if(key == "--deck1") args.deck1 = value;
        else if(key == "--result") args.result = value;
        else if(key == "--seed") args.seed = number(value);
        else if(key == "--policy") {
            if(value == "pass") args.policy = yda::SmokePolicy::Pass;
            else if(value == "hinotama-smoke") args.policy = yda::SmokePolicy::Hinotama;
            else throw std::runtime_error("Unknown smoke policy: " + value);
        } else if(key == "--required-main") {
            const auto at = value.find('=');
            if(at == std::string::npos)
                throw std::runtime_error("Required Main format must be code=count");
            const uint64_t code = number(value.substr(0, at));
            const uint64_t count = number(value.substr(at + 1));
            if(code == 0 || code > UINT32_MAX || count == 0 || count > 3)
                throw std::runtime_error("Invalid required Main card/count");
            auto inserted = args.required.emplace(static_cast<uint32_t>(code), static_cast<unsigned>(count));
            if(!inserted.second)
                throw std::runtime_error("Repeated required Main card");
        } else throw std::runtime_error("Unknown argument: " + key);
    }
    if(args.db.empty() || args.deck0.empty() || args.deck1.empty())
        throw std::runtime_error("Required arguments: --db --deck0 --deck1");
    if(!args.validate_only && args.scripts.empty())
        throw std::runtime_error("--scripts is required for a duel");
}
std::string json_string(const std::string& text)
{
    std::string out = "\"";
    for(unsigned char c : text) {
        if(c == '"' || c == '\\') { out += '\\'; out += static_cast<char>(c); }
        else if(c < 32) {
            char escaped[7];
            std::snprintf(escaped, sizeof(escaped), "\\u%04x", unsigned(c));
            out += escaped;
        } else out += static_cast<char>(c);
    }
    return out + '"';
}
void write_result(const Arguments& args, const Result& result)
{
    if(args.result.empty())
        return;
    if(!args.result.parent_path().empty())
        std::filesystem::create_directories(args.result.parent_path());
    std::ofstream file(args.result);
    if(!file)
        throw std::runtime_error("Cannot write result file");
    file << "{\n  \"schema\":1,\n  \"profile\":\"mr5-no-banlist-smoke-v1\",\n"
         << "  \"engine_api\":\"11.0\",\n  \"policy\":"
         << json_string(args.policy == yda::SmokePolicy::Pass ? "pass" : "hinotama-smoke")
         << ",\n  \"seed\": " << args.seed << ",\n  \"seed_words\":[" << args.seed << ",2,3,4],\n"
         << "  \"first_player\":0,\n  \"status\":" << json_string(result.status)
         << ",\n  \"error\":" << json_string(result.error)
         << ",\n  \"winner\":" << (result.winner < 0 ? "null" : std::to_string(result.winner))
         << ",\n  \"reason\":" << (result.reason < 0 ? "null" : std::to_string(result.reason));
    file << ",\n  \"process_calls\":" << result.calls << ",\n  \"turns\":" << result.turns
         << ",\n  \"activations\":" << result.activations << ",\n  \"chains_solved\":" << result.solved
         << ",\n  \"damage_events\":" << result.damage_events << ",\n  \"effect_damage\":" << result.damage
         << ",\n  \"scripts_loaded\":" << result.scripts << ",\n  \"optional_scripts_missing\":" << result.optional_scripts
         << ",\n  \"engine_errors\":" << result.engine_errors << ",\n  \"card_reads\":" << result.card_reads;
    file << ",\n  \"main\":[" << result.main[0] << ',' << result.main[1]
         << "],\n  \"extra\":[" << result.extra[0] << ',' << result.extra[1]
         << "],\n  \"side\":[" << result.side[0] << ',' << result.side[1]
         << "],\n  \"deck_files\":[" << json_string(args.deck0.generic_string()) << ','
         << json_string(args.deck1.generic_string()) << "]\n}\n";
    if(!file.flush())
        throw std::runtime_error("Failed to flush result file");
}

void run(const Arguments& args, Result& result)
{
    yda::CardDatabase db(args.db);
    yda::Deck decks[] = {yda::load_ydk(args.deck0), yda::load_ydk(args.deck1)};
    yda::validate_deck(decks[0], db, args.required);
    yda::validate_deck(decks[1], db);
    for(unsigned p = 0; p < 2; ++p) {
        result.main[p] = decks[p].main.size();
        result.extra[p] = decks[p].extra.size();
        result.side[p] = decks[p].side.size();
    }
    std::cout << "Database loaded: " << db.size() << " records\n"
              << "Profile: mr5-no-banlist-smoke-v1 (NOT tournament legality)\n"
              << "Decks validated: " << result.main[0] << '/' << result.main[1] << " Main\n";
    if(args.validate_only) { result.status = "validated"; return; }
    // 범용 AI가 아닌 fixture 전용 정책이다. 지원 밖의 덱을 조용히 패스 평가하지 않는다.
    for(const auto& deck : decks) {
        for(uint32_t code : deck.main) {
            const auto* card = db.find(code);
            if(card->data.type != (TYPE_MONSTER | TYPE_NORMAL) &&
               !(args.policy == yda::SmokePolicy::Hinotama && code == yda::hinotama_code))
                throw std::runtime_error("Smoke policy does not support Main card " + std::to_string(code));
        }
    }
    int major = 0, minor = 0;
    OCG_GetVersion(&major, &minor);
    if(major != 11 || minor != 0)
        throw std::runtime_error("Expected pinned OCGCore API 11.0");
    result.status = "resource_error";
    yda::CardReaderContext reader{db};
    yda::ScriptLoader scripts(args.scripts, db);
    DuelGuard duel;
    OCG_DuelOptions options{};
    options.seed[0] = args.seed;
    options.seed[1] = 2; options.seed[2] = 3; options.seed[3] = 4;
    options.flags = DUEL_MODE_MR5;
    options.team1 = {8000, 5, 1}; options.team2 = {8000, 5, 1};
    options.cardReader = yda::CardReaderContext::read; options.payload1 = &reader;
    options.cardReaderDone = yda::CardReaderContext::release; options.payload4 = &reader;
    options.scriptReader = yda::ScriptLoader::read; options.payload2 = &scripts;
    options.logHandler = yda::ScriptLoader::log; options.payload3 = &scripts;
    // unsafe Lua io/dofile/loadfile는 켜지 않는다.
    auto resources_ok = [&]() {
        result.scripts = scripts.loaded_count();
        result.optional_scripts = scripts.optional_missing;
        result.engine_errors = scripts.engine_errors;
        result.card_reads = reader.reads;
        if(reader.failed || scripts.failed()) {
            result.status = "resource_error";
            throw std::runtime_error(reader.failed ? "CardReader: missing code " + std::to_string(reader.missing_code)
                                                   : scripts.error());
        }
    };
    const int created = OCG_CreateDuel(&duel.value, &options);
    if(created != OCG_DUEL_CREATION_SUCCESS || !duel.value)
        throw std::runtime_error("OCG_CreateDuel failed: " + std::to_string(created));
    resources_ok();
    scripts.bootstrap(duel.value);
    resources_ok();
    std::cout << "Common Lua loaded: " << scripts.loaded_count() << " files\n";
    for(uint8_t player = 0; player < 2; ++player) {
        const std::vector<uint32_t>* sections[] = {&decks[player].main, &decks[player].extra};
        for(unsigned section = 0; section < 2; ++section) {
            for(uint32_t code : *sections[section]) {
                OCG_NewCardInfo card{};
                card.team = player; card.duelist = 0; card.code = code; card.con = player;
                card.loc = section == 0 ? LOCATION_DECK : LOCATION_EXTRA;
                card.pos = POS_FACEDOWN_DEFENSE;
                OCG_DuelNewCard(duel.value, &card);
                resources_ok();
            }
        }
        if(OCG_DuelQueryCount(duel.value, player, LOCATION_DECK) != result.main[player] ||
           OCG_DuelQueryCount(duel.value, player, LOCATION_EXTRA) != result.extra[player])
            throw std::runtime_error("Deck count mismatch after injection");
    }
    std::cout << "Deck injection verified; Side remains outside the duel.\n";
    OCG_StartDuel(duel.value);
    resources_ok();
    result.status = "protocol_error";
    std::optional<yda::Response> pending;
    constexpr uint64_t process_limit = 10000;
    for(uint64_t i = 0; i < process_limit; ++i) {
        const int status = OCG_DuelProcess(duel.value);
        ++result.calls;
        resources_ok();
        uint32_t length = 0;
        const auto* bytes = static_cast<const uint8_t*>(OCG_DuelGetMessage(duel.value, &length));
        if(length && !bytes)
            throw yda::ProtocolError("Nonempty message has null buffer");
        uint32_t offset = 0;
        while(offset < length) {
            DecodedMessage message{};
            if(!decode_next_message(bytes, length, &offset, &message))
                throw yda::ProtocolError("Malformed message frame");
            const auto* p = message.payload;
            if(message.type == MSG_RETRY)
                throw yda::ProtocolError("OCGCore rejected a response (MSG_RETRY)");
            if(message.type == MSG_WIN) {
                if(message.payload_size != 3 || p[1] > 2 || result.winner != -1 || pending)
                    throw yda::ProtocolError("Malformed/duplicate WIN or unfinished selection");
                result.winner = p[1]; result.reason = p[2];
            } else if(yda::is_selection(message.type)) {
                if(pending || result.winner != -1)
                    throw yda::ProtocolError("Multiple pending selections or selection after WIN");
                pending = yda::smoke_response(message, args.policy);
            } else if(message.type == MSG_NEW_TURN) {
                if(message.payload_size != 2 || p[1] > 1)
                    throw yda::ProtocolError("Malformed NEW_TURN");
                ++result.turns;
            } else if(message.type == MSG_CHAIN_SOLVED) {
                if(message.payload_size != 2)
                    throw yda::ProtocolError("Malformed CHAIN_SOLVED");
                ++result.solved;
            } else if(message.type == MSG_DAMAGE) {
                if(message.payload_size != 6 || p[1] > 1)
                    throw yda::ProtocolError("Malformed DAMAGE");
                const uint32_t amount = yda::read_u32(p + 2);
                if(args.policy != yda::SmokePolicy::Hinotama || amount != 500)
                    throw yda::ProtocolError("Unexpected damage for this fixture");
                ++result.damage_events;
                result.damage += amount;
                std::cout << "Effect damage: player=" << unsigned(p[1]) << " amount=" << amount << '\n';
            }
        }
        if(status != OCG_DUEL_STATUS_END && status != OCG_DUEL_STATUS_AWAITING &&
           status != OCG_DUEL_STATUS_CONTINUE)
            throw yda::ProtocolError("Unknown process status");
        if(result.winner != -1) {
            if(args.policy == yda::SmokePolicy::Hinotama &&
               (!result.activations || !result.solved || !result.damage_events ||
                !scripts.loaded("c46130346.lua"))) {
                result.status = "effect_not_exercised";
                throw std::runtime_error("WIN without the required real Lua effect evidence");
            }
            result.status = "finished";
            std::cout << "PHASE2 PASS: winner=" << result.winner << " reason=" << result.reason
                      << " activations=" << result.activations << " damage_events=" << result.damage_events
                      << " script_errors=" << result.engine_errors << '\n';
            return;
        }
        if(status == OCG_DUEL_STATUS_END) {
            result.status = "no_result";
            throw std::runtime_error("END without MSG_WIN is not a normal result");
        }
        if(status == OCG_DUEL_STATUS_AWAITING) {
            if(!pending)
                throw yda::UnsupportedSelection("AWAITING without a supported pending selection");
            if(pending->activated_code) {
                ++result.activations;
                std::cout << "Activate: " << pending->activated_code << '\n';
            }
            OCG_DuelSetResponse(duel.value, pending->bytes.data(), static_cast<uint32_t>(pending->bytes.size()));
            pending.reset();
        }
        // CONTINUE 뒤 빈 AWAITING이 오는 경우에도 pending을 유지한다.
    }
    result.status = "limit_exceeded";
    throw std::runtime_error("Process call limit exceeded");
}
}

int main(int argc, char** argv)
{
    Arguments args;
    Result result;
    try {
        parse(argc, argv, args);
        run(args, result);
    } catch(const yda::UnsupportedSelection& error) {
        result.status = "unsupported_selection"; result.error = error.what();
    } catch(const yda::ProtocolError& error) {
        result.status = "protocol_error"; result.error = error.what();
    } catch(const std::exception& error) {
        result.error = error.what();
    }
    const bool passed = result.status == "finished" || result.status == "validated";
    if(!passed) {
        // 오류 뒤 받은 WIN이 있더라도 정상 승패 필드로 내보내지 않는다.
        result.winner = -1; result.reason = -1;
        std::cerr << "PHASE2 FAIL [" << result.status << "]: " << result.error << '\n';
    }
    try { write_result(args, result); }
    catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
    return passed ? 0 : 1;
}
