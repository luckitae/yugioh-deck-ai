#include "script_loader.h"
#include "ocgapi.h"
#include "ocgapi_constants.h"
#include <charconv>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <vector>

namespace yda {
namespace {
bool card_script(const std::string& name, uint32_t& code)
{
    if(name.size() < 6 || name.front() != 'c' ||
       name.compare(name.size() - 4, 4, ".lua") != 0)
        return false;
    const auto result = std::from_chars(name.data() + 1, name.data() + name.size() - 4, code);
    return result.ec == std::errc() && result.ptr == name.data() + name.size() - 4;
}

void check_name(const std::string& name)
{
    const std::filesystem::path path(name);
    if(name.empty() || name.size() > 240 || name.find('\0') != std::string::npos ||
       name.find('\\') != std::string::npos || path.is_absolute() ||
       path.has_root_name() || path.extension() != ".lua")
        throw std::runtime_error("Script: unsafe or invalid script name");
    for(const auto& part : path) {
        if(part == "." || part == "..")
            throw std::runtime_error("Script: path traversal rejected");
    }
}
}

ScriptLoader::ScriptLoader(const std::filesystem::path& root, const CardDatabase& db)
    : database_(db), root_(std::filesystem::canonical(root))
{
    if(!std::filesystem::is_directory(root_))
        throw std::runtime_error("Script root is not a directory");
}

void ScriptLoader::fail(const char* message) noexcept
{
    if(!failed_)
        std::snprintf(error_.data(), error_.size(), "%s", message ? message : "unknown script error");
    failed_ = true;
}

bool ScriptLoader::optional(const std::string& name) const
{
    uint32_t code = 0;
    if(!card_script(name, code))
        return false;
    if(code == 0)
        return true; // OCG_CreateDuel 중 생성되는 내부 임시 카드.
    const CardRecord* record = database_.find(code);
    return record && (record->data.type & TYPE_NORMAL) &&
           !(record->data.type & TYPE_PENDULUM);
}

int ScriptLoader::load(OCG_Duel duel, const std::string& name, bool allow_normal_missing)
{
    check_name(name);
    if(!duel)
        throw std::runtime_error("Script: null duel");
    auto found = cache_.find(name);
    if(found == cache_.end()) {
        uint32_t code = 0;
        const bool is_card = card_script(name, code);
        std::vector<std::filesystem::path> candidates{root_ / name, root_ / "official" / name};
        // utility.lua가 요청하는 proc_unofficial.lua 등 공통 helper만 허용한다.
        // 카드 c<ID>.lua를 unofficial/pre-errata로 조용히 대체하지 않는다.
        if(!is_card)
            candidates.push_back(root_ / "unofficial" / name);
        std::filesystem::path resolved;
        for(const auto& candidate : candidates) {
            if(!std::filesystem::exists(candidate))
                continue;
            const auto canonical = std::filesystem::canonical(candidate);
            const auto relative = canonical.lexically_relative(root_);
            if(relative.empty() || *relative.begin() == "..")
                throw std::runtime_error("Script: symlink escapes script root");
            if(!std::filesystem::is_regular_file(canonical))
                throw std::runtime_error("Script: expected a regular file");
            resolved = canonical;
            break;
        }
        if(resolved.empty()) {
            if(allow_normal_missing && optional(name)) {
                ++optional_missing;
                return 0;
            }
            throw std::runtime_error("Script missing: " + name);
        }
        const auto length = std::filesystem::file_size(resolved);
        if(length == 0 || length > 8u * 1024u * 1024u)
            throw std::runtime_error("Script: empty or oversized file: " + name);
        std::string bytes(static_cast<size_t>(length), '\0');
        std::ifstream file(resolved, std::ios::binary);
        if(!file.read(bytes.data(), static_cast<std::streamsize>(length)))
            throw std::runtime_error("Script read failed: " + name);
        found = cache_.emplace(name, std::move(bytes)).first;
    }
    if(!loading_.insert(name).second)
        throw std::runtime_error("Script: recursive dependency: " + name);
    const auto& bytes = found->second; // std::map 노드는 재귀 로드 중에도 안정적이다.
    const int result = OCG_LoadScript(duel, bytes.data(), static_cast<uint32_t>(bytes.size()), name.c_str());
    loading_.erase(name);
    if(result <= 0)
        throw std::runtime_error("Lua load/execute failed: " + name);
    successful_.insert(name);
    return result;
}

void ScriptLoader::require(OCG_Duel duel, const std::string& name)
{
    try {
        load(duel, name, false);
    } catch(const std::exception& error) {
        fail(error.what());
        throw;
    }
    if(failed_)
        throw std::runtime_error(error());
}

void ScriptLoader::bootstrap(OCG_Duel duel)
{
    require(duel, "constant.lua");
    require(duel, "utility.lua");
}

int ScriptLoader::read(void* payload, OCG_Duel duel, const char* name) noexcept
{
    if(!payload)
        return 0;
    auto& self = *static_cast<ScriptLoader*>(payload);
    try {
        if(!name)
            throw std::runtime_error("Script: null name");
        return self.load(duel, name, true);
    } catch(const std::exception& error) {
        self.fail(error.what());
    } catch(...) {
        self.fail("Script: unexpected callback failure");
    }
    return 0;
}

void ScriptLoader::log(void* payload, const char* message, int type) noexcept
{
    std::fprintf(stderr, "[OCG log type=%d] %s\n", type, message ? message : "(null)");
    if(payload && type == OCG_LOG_TYPE_ERROR) {
        auto& self = *static_cast<ScriptLoader*>(payload);
        ++self.engine_errors;
        self.fail(message);
    }
}
}
