#include <stdio.h>
#include <stdint.h>
#include "ocgapi.h"
#include "ocgapi_constants.h"
#include "message_decoder.h"

static void card_reader(void* payload, uint32_t code, OCG_CardData* data) {
    (void)payload;
    if(code != 1) return;
    data->code = 1;
    data->alias = 0;
    data->setcodes = nullptr;
    data->type = 0;
    data->level = 4;
    data->attribute = 0;
    data->race = 0;
    data->attack = 1000;
    data->defense = 1000;
    data->lscale = 0;
    data->rscale = 0;
    data->link_marker = 0;
}

static int script_reader(void* payload, OCG_Duel duel, const char* name) {
    (void)payload; (void)duel; (void)name;
    return 0;
}

static void log_handler(void* payload, const char* string, int type) {
    (void)payload; (void)string; (void)type;
}

static void card_reader_done(void* payload, OCG_CardData* data) {
    (void)payload; (void)data;
}

static void dump_messages(const void* buffer, uint32_t length) {
    const uint8_t* data = (const uint8_t*)buffer;
    uint32_t offset = 0;
    int count = 0;

    printf("=== Message stream (%u bytes) ===\n", length);
    while(offset < length) {
        DecodedMessage msg = {};
        if(!decode_next_message(data, length, &offset, &msg)) {
            printf("ERROR: malformed message frame at offset %u.\n", offset);
            return;
        }
        printf("message[%d]: type=%u (0x%02X) %s payload=%u bytes\n",
               count, msg.type, msg.type, message_name(msg.type), msg.payload_size);
        if(msg.type == MSG_SELECT_IDLECMD) {
            printf("  payload:");
            for(uint32_t j = 0; j < msg.payload_size; ++j)
                printf(" %02X", msg.payload[j]);
            printf("\n");
        }
        ++count;
    }
    printf("Decoded %d message frame(s).\n", count);
}

int main() {
    int major = 0, minor = 0;
    OCG_GetVersion(&major, &minor);
    printf("OCGCore version: %d.%d\n", major, minor);

    OCG_DuelOptions options = {};
    options.seed[0] = 1; options.seed[1] = 2;
    options.seed[2] = 3; options.seed[3] = 4;
    options.team1.startingLP = 8000;
    options.team1.startingDrawCount = 5;
    options.team1.drawCountPerTurn = 1;
    options.team2.startingLP = 8000;
    options.team2.startingDrawCount = 5;
    options.team2.drawCountPerTurn = 1;
    options.cardReader = card_reader;
    options.scriptReader = script_reader;
    options.logHandler = log_handler;
    options.cardReaderDone = card_reader_done;

    OCG_Duel duel = nullptr;
    int result = OCG_CreateDuel(&duel, &options);
    printf("OCG_CreateDuel result: %d\n", result);
    if(!duel) return 1;

    /* Keep this as a transport/parser smoke test. A legal 40-card deck is a later phase. */
    for(int i = 0; i < 40; ++i) {
        OCG_NewCardInfo card = {};
        card.team = 0;
        card.duelist = 0;
        card.code = 1;
        card.con = 0;
        card.loc = LOCATION_DECK;
        card.seq = (uint8_t)i;
        card.pos = 0;
        OCG_DuelNewCard(duel, &card);
    }
    for(int i = 0; i < 40; ++i) {
        OCG_NewCardInfo card = {};
        card.team = 1;
        card.duelist = 1;
        card.code = 1;
        card.con = 0;
        card.loc = LOCATION_DECK;
        card.seq = (uint8_t)i;
        card.pos = 0;
        OCG_DuelNewCard(duel, &card);
    }
    printf("Test decks added: 40 cards per player.\n");

    OCG_StartDuel(duel);
    printf("Duel started.\n");

    for(int i = 0; i < 100; ++i) {
        int status = OCG_DuelProcess(duel);
        printf("\nDuelProcess[%d] status: %d\n", i, status);

        uint32_t length = 0;
        void* message = OCG_DuelGetMessage(duel, &length);
        if(message && length) dump_messages(message, length);

        if(status == OCG_DUEL_STATUS_END) {
            printf("Duel ended.\n");
            break;
        }

        if(status == OCG_DUEL_STATUS_AWAITING) {
            /* Do not guess a universal response format. Phase 1 only proves decoding. */
            printf("AWAITING: stopping before sending an invalid generic response.\n");
            break;
        }
    }

    OCG_DestroyDuel(duel);
    printf("Duel destroyed successfully.\n");
    return 0;
}
