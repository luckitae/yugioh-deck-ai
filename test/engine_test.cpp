#include <stdio.h>
#include <stdint.h>

#include "ocgapi.h"
#include "ocgapi_constants.h"
#include "message_decoder.h"

static void card_reader(void* payload, uint32_t code, OCG_CardData* data) {
    (void)payload;

    if(code != 1)
        return;

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

static int script_reader(void* payload,
                         OCG_Duel duel,
                         const char* name) {
    (void)payload;
    (void)duel;
    (void)name;

    return 0;
}

static void log_handler(void* payload,
                        const char* string,
                        int type) {
    (void)payload;
    (void)string;
    (void)type;
}

static void card_reader_done(void* payload,
                             OCG_CardData* data) {
    (void)payload;
    (void)data;
}

static void print_idle_command(const DecodedMessage* msg) {
    IdleCmdMessage idle = {};

    if(!decode_idle_cmd(msg, &idle)) {
        printf("ERROR: failed to decode MSG_SELECT_IDLECMD.\n");
        return;
    }

    printf("=== Decoded idle command ===\n");
    printf("player:              %u\n", idle.player);
    printf("summonable:          %u\n", idle.summonable_count);
    printf("special summonable:  %u\n", idle.spsummonable_count);
    printf("repositionable:      %u\n", idle.repositionable_count);
    printf("monster settable:    %u\n", idle.msetable_count);
    printf("spell/trap settable: %u\n", idle.ssetable_count);
    printf("activatable:         %u\n", idle.activate_count);
    printf("to BP:               %u\n", idle.to_bp);
    printf("to EP:               %u\n", idle.to_ep);
    printf("can shuffle:         %u\n", idle.can_shuffle);
}

static uint32_t dump_messages(const void* buffer,
                              uint32_t length) {
    const uint8_t* data = (const uint8_t*)buffer;
    uint32_t offset = 0;
    int count = 0;
    uint32_t awaiting_message = 0;

    printf("=== Message stream (%u bytes) ===\n", length);

    while(offset < length) {
        DecodedMessage msg = {};

        if(!decode_next_message(data,
                                length,
                                &offset,
                                &msg)) {
            printf("ERROR: malformed message frame.\n");
            return 0;
        }

        printf(
            "message[%d]: type=%u (0x%02X) %s payload=%u bytes\n",
            count,
            msg.type,
            msg.type,
            message_name(msg.type),
            msg.payload_size
        );

        if(msg.type == MSG_SELECT_IDLECMD) {
            print_idle_command(&msg);
            awaiting_message = msg.type;
        }

        ++count;
    }

    printf("Decoded %d message frame(s).\n", count);

    return awaiting_message;
}

int main() {
    int major = 0;
    int minor = 0;

    OCG_GetVersion(&major, &minor);

    printf("OCGCore version: %d.%d\n", major, minor);

    OCG_DuelOptions options = {};

    options.seed[0] = 1;
    options.seed[1] = 2;
    options.seed[2] = 3;
    options.seed[3] = 4;

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

    if(!duel)
        return 1;

    /*
     * Phase 1 smoke-test deck.
     *
     * This is deliberately not a real playable deck.
     * The purpose is to test the OCGCore transport/message layer.
     */
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

    uint32_t awaiting_message = 0;

    for(int i = 0; i < 100; ++i) {
        int status = OCG_DuelProcess(duel);

        printf("\nDuelProcess[%d] status: %d\n",
               i,
               status);

        uint32_t length = 0;

        void* message =
            OCG_DuelGetMessage(duel, &length);

        if(message && length)
            awaiting_message = dump_messages(message, length);

        if(status == OCG_DUEL_STATUS_END) {
            printf("Duel ended.\n");
            break;
        }

        if(status == OCG_DUEL_STATUS_AWAITING) {
            if(awaiting_message == MSG_SELECT_IDLECMD) {
                int32_t response = 7;

                printf("AWAITING: sending End Phase response.\n");

                OCG_DuelSetResponse(duel, &response, sizeof(response));

                awaiting_message = 0;
                continue;
            }

            printf("ERROR: unsupported AWAITING message.\n");
            break;
        }
    }

    OCG_DestroyDuel(duel);

    printf("Duel destroyed successfully.\n");

    return 0;
}