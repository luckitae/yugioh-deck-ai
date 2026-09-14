#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <vector>

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

static uint8_t chain_forced = 0;
static uint32_t chain_count = 0;

static uint8_t select_card_cancelable = 0;
static uint32_t select_card_min = 0;
static uint32_t select_card_max = 0;
static uint32_t select_card_count = 0;

static uint32_t read_u32_le_local(const uint8_t* p) {
    return (uint32_t)p[0]
         | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16)
         | ((uint32_t)p[3] << 24);
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
        } else if(msg.type == MSG_SELECT_CHAIN) {
            /*
             * payload[0] = MSG_SELECT_CHAIN
             * payload[1] = player
             * payload[2] = spe_count
             * payload[3] = forced
             * payload[4..7] = hint timing (player)
             * payload[8..11] = hint timing (opponent)
             * payload[12..15] = selectable chain count
             */
            if(msg.payload_size < 16) {
                printf("ERROR: malformed MSG_SELECT_CHAIN.\n");
                return 0;
            }

            chain_forced = msg.payload[3];
            chain_count = read_u32_le_local(msg.payload + 12);
            awaiting_message = msg.type;

            printf("=== Decoded chain selection ===\n");
            printf("forced:              %u\n", chain_forced);
            printf("selectable chains:   %u\n", chain_count);
        } else if(msg.type == MSG_SELECT_CARD) {
            /*
             * payload[0]      = MSG_SELECT_CARD
             * payload[1]      = player
             * payload[2]      = cancelable
             * payload[3..6]   = minimum selection count
             * payload[7..10]  = maximum selection count
             * payload[11..14] = selectable card count
             */
            if(msg.payload_size < 15) {
                printf("ERROR: malformed MSG_SELECT_CARD.\n");
                return 0;
            }

            select_card_cancelable = msg.payload[2];
            select_card_min = read_u32_le_local(msg.payload + 3);
            select_card_max = read_u32_le_local(msg.payload + 7);
            select_card_count = read_u32_le_local(msg.payload + 11);

            if(select_card_min > select_card_max ||
               select_card_max > select_card_count) {
                printf("ERROR: invalid MSG_SELECT_CARD bounds.\n");
                return 0;
            }

            awaiting_message = msg.type;

            printf("=== Decoded card selection ===\n");
            printf("cancelable:           %u\n", select_card_cancelable);
            printf("minimum:              %u\n", select_card_min);
            printf("maximum:              %u\n", select_card_max);
            printf("selectable cards:     %u\n", select_card_count);
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

    for(int i = 0; i < 10000; ++i) {
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

            if(awaiting_message == MSG_SELECT_CHAIN) {
                int32_t response;

                if(chain_forced) {
                    if(chain_count == 0) {
                        printf("ERROR: forced chain selection has no choices.\n");
                        break;
                    }
                    response = 0;
                    printf("AWAITING: selecting forced chain 0.\n");
                } else {
                    response = -1;
                    printf("AWAITING: declining optional chain.\n");
                }

                OCG_DuelSetResponse(duel, &response, sizeof(response));

                awaiting_message = 0;
                chain_forced = 0;
                chain_count = 0;
                continue;
            }

            if(awaiting_message == MSG_SELECT_CARD) {
                /*
                 * parse_response_cards() type 0 format:
                 *
                 * int32_t  type = 0
                 * uint32_t count
                 * uint32_t indices[count]
                 *
                 * The smoke-test bot deterministically selects the first
                 * minimum number of legal cards.
                 */
                if(select_card_min > select_card_count) {
                    printf("ERROR: cannot satisfy card selection minimum.\n");
                    break;
                }

                std::vector<uint8_t> response(
                    8 + select_card_min * sizeof(uint32_t),
                    0
                );

                int32_t type = 0;
                uint32_t count = select_card_min;

                memcpy(response.data(), &type, sizeof(type));
                memcpy(response.data() + 4, &count, sizeof(count));

                for(uint32_t j = 0; j < count; ++j)
                    memcpy(response.data() + 8 + j * 4,
                           &j,
                           sizeof(j));

                printf(
                    "AWAITING: selecting first %u card(s).\n",
                    count
                );

                OCG_DuelSetResponse(
                    duel,
                    response.data(),
                    (uint32_t)response.size()
                );

                awaiting_message = 0;
                select_card_cancelable = 0;
                select_card_min = 0;
                select_card_max = 0;
                select_card_count = 0;
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