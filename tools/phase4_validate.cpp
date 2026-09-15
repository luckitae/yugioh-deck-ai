// Phase 2의 기존 C++ Deck Loader로 생성 YDK를 교차 검증한다.
// 날짜별 금제는 Python RuleProfile 책임이며 이 실행 파일은 구조만 검사한다.
#include "data/card_database.h"
#include "data/deck_loader.h"
#include <charconv>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
uint32_t number(const std::string& input)
{
    uint32_t out = 0;
    const auto parsed = std::from_chars(input.data(), input.data() + input.size(), out);
    if(parsed.ec != std::errc() || parsed.ptr != input.data() + input.size() || out == 0)
        throw std::runtime_error("invalid positive integer: " + input);
    return out;
}
}

int main(int argc, char** argv)
{
    try {
        std::filesystem::path db_path;
        std::vector<std::filesystem::path> paths;
        yda::RequiredMain required;
        for(int i = 1; i < argc; ++i) {
            const std::string key = argv[i];
            if(++i >= argc)
                throw std::runtime_error("missing value: " + key);
            const std::string value = argv[i];
            if(key == "--db") db_path = value;
            else if(key == "--deck") paths.emplace_back(value);
            else if(key == "--required-main") {
                const auto split = value.find('=');
                if(split == std::string::npos)
                    throw std::runtime_error("required format: code=count");
                const auto code = number(value.substr(0, split));
                const auto count = number(value.substr(split + 1));
                if(count > 3 || !required.emplace(code, count).second)
                    throw std::runtime_error("invalid/repeated required count");
            } else throw std::runtime_error("unknown option: " + key);
        }
        if(db_path.empty() || paths.empty() || paths.size() > 10000)
            throw std::runtime_error("--db and 1..10000 --deck paths are required");
        yda::CardDatabase db(db_path);
        for(const auto& path : paths) {
            try {
                yda::validate_deck(yda::load_ydk(path), db, required);
            } catch(const std::exception& error) {
                throw std::runtime_error(path.string() + ": " + error.what());
            }
        }
        std::cout << "PHASE4 VALIDATE PASS: decks=" << paths.size()
                  << " (Phase 2 structural validator; not a duel)\n";
        return 0;
    } catch(const std::exception& error) {
        std::cerr << "PHASE4 VALIDATE FAIL: " << error.what() << '\n';
        return 2;
    }
}
