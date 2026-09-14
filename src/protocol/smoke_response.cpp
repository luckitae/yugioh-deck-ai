#include "smoke_response.h"
#include "ocgapi_constants.h"

namespace yda {
uint32_t read_u32(const uint8_t* p)
{
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) |
           (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
void append_u32(std::vector<uint8_t>& out, uint32_t value)
{
    for(unsigned shift = 0; shift < 32; shift += 8)
        out.push_back(static_cast<uint8_t>(value >> shift));
}

bool is_selection(uint32_t type)
{
    switch(type) {
        case MSG_REQUEST_DECK:
        case MSG_SELECT_BATTLECMD: case MSG_SELECT_IDLECMD:
        case MSG_SELECT_EFFECTYN: case MSG_SELECT_YESNO: case MSG_SELECT_OPTION:
        case MSG_SELECT_CARD: case MSG_SELECT_CHAIN: case MSG_SELECT_PLACE:
        case MSG_SELECT_POSITION: case MSG_SELECT_TRIBUTE: case MSG_SORT_CHAIN:
        case MSG_SELECT_COUNTER: case MSG_SELECT_SUM: case MSG_SELECT_DISFIELD:
        case MSG_SORT_CARD: case MSG_SELECT_UNSELECT_CARD:
        case MSG_ROCK_PAPER_SCISSORS: case MSG_ANNOUNCE_RACE:
        case MSG_ANNOUNCE_ATTRIB: case MSG_ANNOUNCE_CARD: case MSG_ANNOUNCE_NUMBER:
            return true;
        default: return false;
    }
}

namespace {
void require(bool condition, const char* message)
{
    if(!condition)
        throw ProtocolError(message);
}
void entries(uint32_t length, uint32_t header, uint32_t count, uint32_t width)
{
    require(length >= header && count <= max_selection_candidates &&
            uint64_t(header) + uint64_t(count) * width == length,
            "Selection: truncated/oversized candidate array or trailing bytes");
}
}

Response smoke_response(const DecodedMessage& message, SmokePolicy policy)
{
    require(message.payload && message.payload_size >= 2, "Selection: missing player");
    const auto* p = message.payload;
    const uint32_t size = message.payload_size;
    require(p[0] == message.type && p[1] <= 1, "Selection: invalid type/player");
    Response result;
    result.prompt = message.type;
    if(message.type == MSG_SELECT_IDLECMD) {
        IdleCmdMessage idle{};
        require(decode_idle_cmd(&message, &idle) != 0, "IDLE: invalid payload");
        require(idle.to_bp <= 1 && idle.to_ep <= 1 && idle.can_shuffle <= 1,
                "IDLE: invalid flags");
        const uint32_t counts[] = {idle.summonable_count, idle.spsummonable_count,
            idle.repositionable_count, idle.msetable_count, idle.ssetable_count,
            idle.activate_count};
        const uint32_t widths[] = {10, 10, 7, 10, 10, 19};
        uint32_t offset = 2;
        for(unsigned list = 0; list < 6; ++list) {
            require(counts[list] <= max_selection_candidates, "IDLE: too many candidates");
            offset += 4;
            for(uint32_t i = 0; i < counts[list]; ++i) {
                const auto* item = p + offset + i * widths[list];
                require(item[4] <= 1, "IDLE: invalid candidate controller");
            }
            if(list == 5 && policy == SmokePolicy::Hinotama) {
                for(uint32_t i = 0; i < counts[list]; ++i) {
                    const auto* item = p + offset + i * widths[list];
                    if(read_u32(item) == hinotama_code && item[4] == idle.player &&
                       item[5] == LOCATION_HAND && item[18] == 0) {
                        append_u32(result.bytes, (i << 16) | 5u);
                        result.activated_code = hinotama_code;
                        return result;
                    }
                }
            }
            offset += counts[list] * widths[list];
        }
        if(!idle.to_ep)
            throw UnsupportedSelection("IDLE: smoke policy cannot choose a legal End Phase");
        append_u32(result.bytes, 7);
        return result;
    }
    if(message.type == MSG_SELECT_CHAIN) {
        require(size >= 16 && p[3] <= 1, "CHAIN: invalid header");
        const uint32_t count = read_u32(p + 12);
        entries(size, 16, count, 23);
        for(uint32_t i = 0; i < count; ++i)
            require(p[16 + i * 23 + 4] <= 1, "CHAIN: invalid candidate controller");
        require(p[3] == 0 || count > 0, "CHAIN: forced empty selection");
        append_u32(result.bytes, p[3] ? 0u : UINT32_MAX);
        return result;
    }
    if(message.type == MSG_SELECT_CARD) {
        require(size >= 15 && p[2] <= 1, "CARD: invalid header");
        const uint32_t minimum = read_u32(p + 3);
        const uint32_t maximum = read_u32(p + 7);
        const uint32_t count = read_u32(p + 11);
        entries(size, 15, count, 14);
        require(minimum <= maximum && maximum <= count, "CARD: invalid min/max/count");
        for(uint32_t i = 0; i < count; ++i)
            require(p[15 + i * 14 + 4] <= 1, "CARD: invalid candidate controller");
        append_u32(result.bytes, 0); // pinned core의 uint32 index-list 형식
        append_u32(result.bytes, minimum);
        for(uint32_t i = 0; i < minimum; ++i)
            append_u32(result.bytes, i);
        return result;
    }
    if(message.type == MSG_SELECT_PLACE) {
        require(size == 7 && p[2] > 0 && p[2] <= 30, "PLACE: invalid header/count");
        const uint32_t banned = read_u32(p + 3);
        // flag의 0비트가 선택 가능 칸. 16비트 단위는 선택자/상대 기준이다.
        for(unsigned relative = 0; relative < 2; ++relative) {
            for(unsigned zone = 0; zone < 2; ++zone) {
                const unsigned count = zone == 0 ? 7 : 8;
                for(unsigned seq = 0; seq < count; ++seq) {
                    const unsigned bit = relative * 16 + zone * 8 + seq;
                    if((banned & (uint32_t(1) << bit)) == 0) {
                        result.bytes.push_back(static_cast<uint8_t>(p[1] ^ relative));
                        result.bytes.push_back(zone == 0 ? LOCATION_MZONE : LOCATION_SZONE);
                        result.bytes.push_back(static_cast<uint8_t>(seq));
                        if(result.bytes.size() == size_t(p[2]) * 3)
                            return result;
                    }
                }
            }
        }
        throw ProtocolError("PLACE: fewer legal cells than requested");
    }
    throw UnsupportedSelection("Unsupported selection: " + std::to_string(message.type) +
                               " " + message_name(message.type));
}
}
