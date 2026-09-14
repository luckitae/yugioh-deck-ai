#include "card_database.h"
#include "ocgapi_constants.h"
#include <limits>
#include <memory>
#include <stdexcept>
#include <sqlite3.h>

namespace yda {
namespace {
using Database = std::unique_ptr<sqlite3, decltype(&sqlite3_close)>;
using Statement = std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)>;

int64_t integer(sqlite3_stmt* stmt, int column)
{
    if(sqlite3_column_type(stmt, column) != SQLITE_INTEGER)
        throw std::runtime_error("DB: integer column is missing or has the wrong type");
    return sqlite3_column_int64(stmt, column);
}

uint32_t unsigned32(sqlite3_stmt* stmt, int column)
{
    const int64_t value = integer(stmt, column);
    if(value < 0 || uint64_t(value) > UINT32_MAX)
        throw std::runtime_error("DB: uint32 column is out of range");
    return static_cast<uint32_t>(value);
}

int32_t signed32(sqlite3_stmt* stmt, int column)
{
    const int64_t value = integer(stmt, column);
    if(value < INT32_MIN || value > INT32_MAX)
        throw std::runtime_error("DB: int32 column is out of range");
    return static_cast<int32_t>(value);
}

std::string text(sqlite3_stmt* stmt, int column)
{
    if(sqlite3_column_type(stmt, column) != SQLITE_TEXT)
        throw std::runtime_error("DB: missing texts row or invalid text column");
    const auto* bytes = sqlite3_column_text(stmt, column);
    if(!bytes)
        throw std::runtime_error("DB: text conversion failed");
    return {reinterpret_cast<const char*>(bytes),
            static_cast<size_t>(sqlite3_column_bytes(stmt, column))};
}
}

CardDatabase::CardDatabase(const std::filesystem::path& path)
{
    sqlite3* raw = nullptr;
    const int opened = sqlite3_open_v2(path.string().c_str(), &raw,
                                     SQLITE_OPEN_READONLY, nullptr);
    Database db(raw, sqlite3_close);
    if(opened != SQLITE_OK)
        throw std::runtime_error("DB open failed: " + path.string() + ": " +
                                 (raw ? sqlite3_errmsg(raw) : "no handle"));
    sqlite3_stmt* stmt_raw = nullptr;
    const char* sql =
        "SELECT d.id,d.alias,d.setcode,d.type,d.atk,d.def,d.level,d.race,"
        "d.attribute,d.ot,d.category,t.name,t.desc "
        "FROM datas AS d LEFT JOIN texts AS t ON t.id=d.id ORDER BY d.id";
    const int prepared = sqlite3_prepare_v2(db.get(), sql, -1, &stmt_raw, nullptr);
    Statement stmt(stmt_raw, sqlite3_finalize);
    if(prepared != SQLITE_OK)
        throw std::runtime_error("DB schema: " + std::string(sqlite3_errmsg(db.get())));
    int step = SQLITE_OK;
    while((step = sqlite3_step(stmt.get())) == SQLITE_ROW) {
        CardRecord card;
        card.data.code = unsigned32(stmt.get(), 0);
        if(card.data.code == 0)
            throw std::runtime_error("DB: card code 0 is reserved by OCGCore");
        card.data.alias = unsigned32(stmt.get(), 1);
        const uint64_t packed_sets = static_cast<uint64_t>(integer(stmt.get(), 2));
        size_t n = 0;
        for(unsigned i = 0; i < 4; ++i) {
            const auto code = static_cast<uint16_t>((packed_sets >> (16 * i)) & 0xffffu);
            if(code != 0)
                card.setcodes[n++] = code;
        }
        card.data.type = unsigned32(stmt.get(), 3);
        card.data.attack = signed32(stmt.get(), 4);
        const int32_t defense = signed32(stmt.get(), 5);
        card.data.defense = (card.data.type & TYPE_LINK) ? 0 : defense;
        card.data.link_marker = (card.data.type & TYPE_LINK)
                                   ? static_cast<uint32_t>(defense) : 0;
        // EDOPro CDB: 하위 8비트 레벨, 24..31 L scale, 16..23 R scale.
        const int64_t raw_level = integer(stmt.get(), 6);
        if(raw_level < INT32_MIN || raw_level > UINT32_MAX)
            throw std::runtime_error("DB: packed level is out of range");
        const uint32_t packed_level = static_cast<uint32_t>(raw_level);
        const int32_t level = static_cast<int32_t>(packed_level & 0xffu);
        card.data.level = static_cast<uint32_t>(raw_level < 0 ? -level : level);
        card.data.lscale = (packed_level >> 24) & 0xffu;
        card.data.rscale = (packed_level >> 16) & 0xffu;
        card.data.race = static_cast<uint64_t>(integer(stmt.get(), 7));
        card.data.attribute = unsigned32(stmt.get(), 8);
        card.scope = unsigned32(stmt.get(), 9);
        card.category = static_cast<uint64_t>(integer(stmt.get(), 10));
        card.name = text(stmt.get(), 11);
        card.text = text(stmt.get(), 12);
        const auto code = card.data.code;
        if(!cards_.emplace(code, std::move(card)).second)
            throw std::runtime_error("DB: duplicate id " + std::to_string(code));
    }
    if(step != SQLITE_DONE)
        throw std::runtime_error("DB read failed: " + std::string(sqlite3_errmsg(db.get())));
    if(cards_.empty())
        throw std::runtime_error("DB: no card records");
}

const CardRecord* CardDatabase::find(uint32_t code) const noexcept
{
    const auto found = cards_.find(code);
    return found == cards_.end() ? nullptr : &found->second;
}

void CardReaderContext::read(void* payload, uint32_t code, OCG_CardData* out) noexcept
{
    if(!payload || !out)
        return;
    auto& self = *static_cast<CardReaderContext*>(payload);
    *out = {};
    ++self.reads;
    // code 0은 엔진 내부 임시 카드이다. 실제 YDK에서는 허용하지 않는다.
    if(code == 0)
        return;
    const CardRecord* card = self.database.find(code);
    if(!card) {
        if(!self.failed)
            self.missing_code = code;
        self.failed = true;
        return;
    }
    *out = card->data;
    // ABI는 mutable 포인터지만 코어는 이 배열을 읽어 복사하기만 한다.
    out->setcodes = const_cast<uint16_t*>(card->setcodes.data());
}

void CardReaderContext::release(void* payload, OCG_CardData*) noexcept
{
    if(payload)
        ++static_cast<CardReaderContext*>(payload)->done;
    // 배열은 CardDatabase 소유다. 콜백 완료 시 해제하지 않는다.
}
}
