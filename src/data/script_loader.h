#ifndef YDA_SCRIPT_LOADER_H
#define YDA_SCRIPT_LOADER_H
#include "card_database.h"
#include <array>
#include <map>
#include <set>

namespace yda {
class ScriptLoader {
public:
    ScriptLoader(const std::filesystem::path& root, const CardDatabase& db);
    void bootstrap(OCG_Duel duel);
    void require(OCG_Duel duel, const std::string& name);
    bool failed() const noexcept { return failed_; }
    const char* error() const noexcept { return error_.data(); }
    uint64_t loaded_count() const noexcept { return successful_.size(); }
    bool loaded(const std::string& name) const { return successful_.count(name) != 0; }
    uint64_t optional_missing = 0;
    uint64_t engine_errors = 0;
    static int read(void* payload, OCG_Duel duel, const char* name) noexcept;
    static void log(void* payload, const char* message, int type) noexcept;
private:
    int load(OCG_Duel duel, const std::string& name, bool allow_normal_missing);
    bool optional(const std::string& name) const;
    void fail(const char* message) noexcept;
    const CardDatabase& database_;
    std::filesystem::path root_;
    std::map<std::string, std::string> cache_;
    std::set<std::string> loading_;
    std::set<std::string> successful_;
    bool failed_ = false;
    std::array<char, 1024> error_{};
};
}
#endif
