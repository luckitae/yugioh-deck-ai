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

int decode_next_message(const uint8_t* buffer, uint32_t length,
                        uint32_t* offset, DecodedMessage* out) {
    if(!buffer || !offset || !out || *offset > length)
        return 0;
    if(length - *offset < 4)
        return 0;

    const uint8_t* frame = buffer + *offset;
    uint32_t size = read_u32_le(frame);
    if(size == 0 || size > length - *offset - 4)
        return 0;

    const uint8_t* payload = frame + 4;
    out->type = payload[0];
    out->payload = payload;
    out->payload_size = size;
    *offset += 4 + size;
    return 1;
}
