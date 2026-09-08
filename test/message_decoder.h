#ifndef YGO_MESSAGE_DECODER_H
#define YGO_MESSAGE_DECODER_H

#include <stdint.h>
#include <stddef.h>

struct DecodedMessage {
    uint32_t type;
    const uint8_t* payload;
    uint32_t payload_size;
};

const char* message_name(uint32_t type);

/*
 * OCG_DuelGetMessage() returns one or more frames:
 *
 *   uint32_t payload_size
 *   uint8_t  payload[payload_size]
 *
 * The first byte of each payload is the MSG_* value.
 */
int decode_next_message(const uint8_t* buffer,
                        uint32_t length,
                        uint32_t* offset,
                        DecodedMessage* out);

/*
 * Decoded MSG_SELECT_IDLECMD.
 *
 * The actual card entries remain inside the original message buffer.
 * This structure only records their counts and the final flags.
 */
struct IdleCmdMessage {
    uint8_t player;

    uint32_t summonable_count;
    uint32_t spsummonable_count;
    uint32_t repositionable_count;
    uint32_t msetable_count;
    uint32_t ssetable_count;
    uint32_t activate_count;

    uint8_t to_bp;
    uint8_t to_ep;
    uint8_t can_shuffle;
};

int decode_idle_cmd(const DecodedMessage* msg,
                    IdleCmdMessage* out);

#endif