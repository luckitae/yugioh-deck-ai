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
 *   uint32_t payload_size
 *   uint8_t  payload[payload_size]
 *
 * The first byte of each payload is the MSG_* value.
 */
int decode_next_message(const uint8_t* buffer, uint32_t length,
                        uint32_t* offset, DecodedMessage* out);

#endif
