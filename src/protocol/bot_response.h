#ifndef YDA_BOT_RESPONSE_H
#define YDA_BOT_RESPONSE_H

#include "data/card_database.h"
#include "message_decoder.h"
#include <cstdint>
#include <string>
#include <vector>

namespace yda {

struct BotResponse {
    uint32_t prompt = 0;
    uint8_t player = 0;
    uint32_t selected_code = 0;
    uint32_t selected_index = UINT32_MAX;
    std::string action;
    std::vector<uint8_t> bytes;
};

bool is_bot_selection(uint32_t type);
BotResponse first_legal_response(const DecodedMessage& message, const CardDatabase* database = nullptr);

}

#endif
