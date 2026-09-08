#include "message_decoder.h"
#include "ocgapi_constants.h"

static uint32_t read_u32_le(const uint8_t* p) {
    return ((uint32_t)p[0]) |
           ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

const char* message_name(uint32_t type) {
    switch(type) {
        case MSG_RETRY: return "MSG_RETRY";
        case MSG_HINT: return "MSG_HINT";
        case MSG_WAITING: return "MSG_WAITING";
        case MSG_START: return "MSG_START";
        case MSG_WIN: return "MSG_WIN";
        case MSG_UPDATE_DATA: return "MSG_UPDATE_DATA";
        case MSG_UPDATE_CARD: return "MSG_UPDATE_CARD";
        case MSG_REQUEST_DECK: return "MSG_REQUEST_DECK";
        case MSG_SELECT_BATTLECMD: return "MSG_SELECT_BATTLECMD";
        case MSG_SELECT_IDLECMD: return "MSG_SELECT_IDLECMD";
        case MSG_SELECT_EFFECTYN: return "MSG_SELECT_EFFECTYN";
        case MSG_SELECT_YESNO: return "MSG_SELECT_YESNO";
        case MSG_SELECT_OPTION: return "MSG_SELECT_OPTION";
        case MSG_SELECT_CARD: return "MSG_SELECT_CARD";
        case MSG_SELECT_CHAIN: return "MSG_SELECT_CHAIN";
        case MSG_SELECT_PLACE: return "MSG_SELECT_PLACE";
        case MSG_SELECT_POSITION: return "MSG_SELECT_POSITION";
        case MSG_SELECT_TRIBUTE: return "MSG_SELECT_TRIBUTE";
        case MSG_SORT_CHAIN: return "MSG_SORT_CHAIN";
        case MSG_SELECT_COUNTER: return "MSG_SELECT_COUNTER";
        case MSG_SELECT_SUM: return "MSG_SELECT_SUM";
        case MSG_SELECT_DISFIELD: return "MSG_SELECT_DISFIELD";
        case MSG_SORT_CARD: return "MSG_SORT_CARD";
        case MSG_SELECT_UNSELECT_CARD: return "MSG_SELECT_UNSELECT_CARD";
        case MSG_CONFIRM_DECKTOP: return "MSG_CONFIRM_DECKTOP";
        case MSG_CONFIRM_CARDS: return "MSG_CONFIRM_CARDS";
        case MSG_SHUFFLE_DECK: return "MSG_SHUFFLE_DECK";
        case MSG_SHUFFLE_HAND: return "MSG_SHUFFLE_HAND";
        case MSG_REFRESH_DECK: return "MSG_REFRESH_DECK";
        case MSG_SWAP_GRAVE_DECK: return "MSG_SWAP_GRAVE_DECK";
        case MSG_SHUFFLE_SET_CARD: return "MSG_SHUFFLE_SET_CARD";
        case MSG_REVERSE_DECK: return "MSG_REVERSE_DECK";
        case MSG_DECK_TOP: return "MSG_DECK_TOP";
        case MSG_SHUFFLE_EXTRA: return "MSG_SHUFFLE_EXTRA";
        case MSG_NEW_TURN: return "MSG_NEW_TURN";
        case MSG_NEW_PHASE: return "MSG_NEW_PHASE";
        case MSG_CONFIRM_EXTRATOP: return "MSG_CONFIRM_EXTRATOP";
        case MSG_MOVE: return "MSG_MOVE";
        case MSG_POS_CHANGE: return "MSG_POS_CHANGE";
        case MSG_SET: return "MSG_SET";
        case MSG_SWAP: return "MSG_SWAP";
        case MSG_FIELD_DISABLED: return "MSG_FIELD_DISABLED";
        case MSG_SUMMONING: return "MSG_SUMMONING";
        case MSG_SUMMONED: return "MSG_SUMMONED";
        case MSG_SPSUMMONING: return "MSG_SPSUMMONING";
        case MSG_SPSUMMONED: return "MSG_SPSUMMONED";
        case MSG_FLIPSUMMONING: return "MSG_FLIPSUMMONING";
        case MSG_FLIPSUMMONED: return "MSG_FLIPSUMMONED";
        case MSG_CHAINING: return "MSG_CHAINING";
        case MSG_CHAINED: return "MSG_CHAINED";
        case MSG_CHAIN_SOLVING: return "MSG_CHAIN_SOLVING";
        case MSG_CHAIN_SOLVED: return "MSG_CHAIN_SOLVED";
        case MSG_CHAIN_END: return "MSG_CHAIN_END";
        case MSG_CHAIN_NEGATED: return "MSG_CHAIN_NEGATED";
        case MSG_CHAIN_DISABLED: return "MSG_CHAIN_DISABLED";
        case MSG_CARD_SELECTED: return "MSG_CARD_SELECTED";
        case MSG_RANDOM_SELECTED: return "MSG_RANDOM_SELECTED";
        case MSG_BECOME_TARGET: return "MSG_BECOME_TARGET";
        case MSG_DRAW: return "MSG_DRAW";
        case MSG_DAMAGE: return "MSG_DAMAGE";
        case MSG_RECOVER: return "MSG_RECOVER";
        case MSG_EQUIP: return "MSG_EQUIP";
        case MSG_LPUPDATE: return "MSG_LPUPDATE";
        case MSG_UNEQUIP: return "MSG_UNEQUIP";
        case MSG_CARD_TARGET: return "MSG_CARD_TARGET";
        case MSG_CANCEL_TARGET: return "MSG_CANCEL_TARGET";
        case MSG_PAY_LPCOST: return "MSG_PAY_LPCOST";
        case MSG_ADD_COUNTER: return "MSG_ADD_COUNTER";
        case MSG_REMOVE_COUNTER: return "MSG_REMOVE_COUNTER";
        case MSG_ATTACK: return "MSG_ATTACK";
        case MSG_BATTLE: return "MSG_BATTLE";
        case MSG_ATTACK_DISABLED: return "MSG_ATTACK_DISABLED";
        case MSG_DAMAGE_STEP_START: return "MSG_DAMAGE_STEP_START";
        case MSG_DAMAGE_STEP_END: return "MSG_DAMAGE_STEP_END";
        case MSG_MISSED_EFFECT: return "MSG_MISSED_EFFECT";
        case MSG_BE_CHAIN_TARGET: return "MSG_BE_CHAIN_TARGET";
        case MSG_CREATE_RELATION: return "MSG_CREATE_RELATION";
        case MSG_RELEASE_RELATION: return "MSG_RELEASE_RELATION";
        default: return "UNKNOWN";
    }
}

int decode_next_message(const uint8_t* buffer,
                        uint32_t length,
                        uint32_t* offset,
                        DecodedMessage* out) {
    if(!buffer || !offset || !out)
        return 0;

    if(*offset > length)
        return 0;

    if(length - *offset < 4)
        return 0;

    const uint8_t* frame = buffer + *offset;

    uint32_t size = read_u32_le(frame);

    /*
     * A frame must contain at least the message type byte.
     */
    if(size == 0)
        return 0;

    if(size > length - *offset - 4)
        return 0;

    const uint8_t* payload = frame + 4;

    out->type = payload[0];
    out->payload = payload;
    out->payload_size = size;

    *offset += 4 + size;

    return 1;
}

/*
 * Skip count entries of fixed size.
 *
 * This does not decode the entries. It only validates that the
 * complete array exists inside the message.
 */
static int skip_entries(const uint8_t* data,
                        uint32_t size,
                        uint32_t* offset,
                        uint32_t count,
                        uint32_t entry_size) {
    if(!data || !offset)
        return 0;

    if(*offset > size)
        return 0;

    if(entry_size == 0)
        return 0;

    if(count > (size - *offset) / entry_size)
        return 0;

    *offset += count * entry_size;

    return 1;
}

/*
 * MSG_SELECT_IDLECMD layout from playerop.cpp:
 *
 *   uint8_t  playerid
 *
 *   uint32_t summonable_count
 *   summonable_count * 10 bytes
 *
 *   uint32_t spsummonable_count
 *   spsummonable_count * 10 bytes
 *
 *   uint32_t repositionable_count
 *   repositionable_count * 7 bytes
 *
 *   uint32_t msetable_count
 *   msetable_count * 10 bytes
 *
 *   uint32_t ssetable_count
 *   ssetable_count * 10 bytes
 *
 *   uint32_t activate_count
 *   activate_count * 19 bytes
 *
 *   uint8_t to_bp
 *   uint8_t to_ep
 *   uint8_t can_shuffle
 *
 * Normal card entry:
 *
 *   uint32_t code
 *   uint8_t  controller
 *   uint8_t  location
 *   uint32_t sequence
 *
 * = 10 bytes
 *
 * Reposition entry:
 *
 *   uint32_t code
 *   uint8_t  controller
 *   uint8_t  location
 *   uint8_t  sequence
 *
 * = 7 bytes
 *
 * Activate entry:
 *
 *   uint32_t code
 *   uint8_t  controller
 *   uint8_t  location
 *   uint32_t sequence
 *   uint64_t description
 *   uint8_t  client_mode
 *
 * = 19 bytes
 */
int decode_idle_cmd(const DecodedMessage* msg,
                    IdleCmdMessage* out) {
    if(!msg || !out)
        return 0;

    if(msg->type != MSG_SELECT_IDLECMD)
        return 0;

    if(!msg->payload || msg->payload_size < 1)
        return 0;

    const uint8_t* data = msg->payload;
    const uint32_t size = msg->payload_size;

    uint32_t offset = 0;

    out->player = data[offset++];

    /*
     * summonable
     */
    if(size - offset < 4)
        return 0;

    out->summonable_count = read_u32_le(data + offset);
    offset += 4;

    if(!skip_entries(data, size, &offset,
                     out->summonable_count, 10))
        return 0;

    /*
     * special summon
     */
    if(size - offset < 4)
        return 0;

    out->spsummonable_count = read_u32_le(data + offset);
    offset += 4;

    if(!skip_entries(data, size, &offset,
                     out->spsummonable_count, 10))
        return 0;

    /*
     * reposition
     */
    if(size - offset < 4)
        return 0;

    out->repositionable_count = read_u32_le(data + offset);
    offset += 4;

    if(!skip_entries(data, size, &offset,
                     out->repositionable_count, 7))
        return 0;

    /*
     * monster set
     */
    if(size - offset < 4)
        return 0;

    out->msetable_count = read_u32_le(data + offset);
    offset += 4;

    if(!skip_entries(data, size, &offset,
                     out->msetable_count, 10))
        return 0;

    /*
     * spell/trap set
     */
    if(size - offset < 4)
        return 0;

    out->ssetable_count = read_u32_le(data + offset);
    offset += 4;

    if(!skip_entries(data, size, &offset,
                     out->ssetable_count, 10))
        return 0;

    /*
     * activate
     */
    if(size - offset < 4)
        return 0;

    out->activate_count = read_u32_le(data + offset);
    offset += 4;

    if(!skip_entries(data, size, &offset,
                     out->activate_count, 19))
        return 0;

    /*
     * Final flags.
     */
    if(size - offset != 3)
        return 0;

    out->to_bp = data[offset++];
    out->to_ep = data[offset++];
    out->can_shuffle = data[offset++];

    return offset == size;
}