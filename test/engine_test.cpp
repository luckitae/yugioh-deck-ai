#include <stdio.h>
#include <stdint.h>
#include "ocgapi.h"

static void card_reader(void* payload, uint32_t code, OCG_CardData* data) {
    (void)payload;

    if (code != 1)
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

static int script_reader(void* payload, OCG_Duel duel, const char* name) {
    (void)payload;
    (void)duel;
    (void)name;
    return 0;
}

static void log_handler(void* payload, const char* string, int type) {
    (void)payload;
    (void)string;
    (void)type;
}

static void card_reader_done(void* payload, OCG_CardData* data) {
    (void)payload;
    (void)data;
}
static void dump_messages(const void* buffer, uint32_t length) {
    const unsigned char* data =
        (const unsigned char*)buffer;

    printf("=== Message stream (%u bytes) ===\n", length);

    if (length < 4) {
        printf("Message stream too short.\n");
        return;
    }

    uint32_t pos = 0;

    while (pos + 4 <= length) {
        uint32_t type =
            (uint32_t)data[pos]
            | ((uint32_t)data[pos + 1] << 8)
            | ((uint32_t)data[pos + 2] << 16)
            | ((uint32_t)data[pos + 3] << 24);

        printf("Message at offset %u: type=%u (0x%02X)\n",
               pos, type, data[pos]);

        pos += 4;

        /*
         * 아직 메시지별 길이를 정의하지 않는다.
         * 우선 첫 메시지 타입과 전체 버퍼를 확인한다.
         */
        break;
    }

    printf("Raw bytes:");
    for (uint32_t i = 0; i < length; ++i)
        printf(" %02X", data[i]);

    printf("\n");
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
    printf("Duel handle: %p\n", duel);

    if (duel == nullptr) {
        printf("ERROR: Duel was not created.\n");
        return 1;
    }

    OCG_NewCardInfo card = {};

    card.team = 0;
    card.duelist = 0;
    card.code = 1;
    card.con = 0;
    card.loc = 0x01;
    card.seq = 0;
    card.pos = 0;

    OCG_DuelNewCard(duel, &card);
    printf("Test card added successfully.\n");

    OCG_StartDuel(duel);
    printf("Duel started successfully.\n");

    for (int i = 0; i < 100; ++i) {
        int status = OCG_DuelProcess(duel);

        printf("DuelProcess[%d] status: %d\n", i, status);

        if (status == OCG_DUEL_STATUS_END) {
            printf("Duel ended.\n");
            break;
        }

        if (status == OCG_DUEL_STATUS_AWAITING) {
            uint32_t length = 0;
            void* message = OCG_DuelGetMessage(duel, &length);

            printf("Message length: %u\n", length);
            printf("Message pointer: %p\n", message);
	    if (message != nullptr && length > 0) {

                unsigned char* bytes = (unsigned char*)message;

                dump_messages(message, length);

            }  

            if (message == nullptr || length == 0) {
                printf("ERROR: Awaiting state without a message.\n");
                OCG_DestroyDuel(duel);
                return 1;
            }

            printf("Engine is awaiting a response.\n");

            break;
        }
    }

    OCG_DestroyDuel(duel);
    printf("Duel destroyed successfully.\n");

    return 0;
}
