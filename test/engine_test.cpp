#include <stdio.h>
#include <stdint.h>
#include "ocgapi.h"
#include "ocgapi_constants.h"

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

static const char* message_name(uint32_t type) {
    switch (type) {
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
        default: return "UNKNOWN";
    }
}

static void dump_messages(const void* buffer, uint32_t length) {
    const unsigned char* data =
        (const unsigned char*)buffer;

    printf("=== Message stream (%u bytes) ===\n", length);

    if (length < 1) {
        printf("Message stream empty.\n");
        return;
    }

    uint32_t type = data[0];

    printf("First message type: %u (0x%02X) = %s\n",
           type, type, message_name(type));

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

    for (int i = 0; i < 20; ++i) {
        int status = OCG_DuelProcess(duel);

        printf("\nDuelProcess[%d] status: %d\n", i, status);

        if (status == OCG_DUEL_STATUS_END) {
            printf("Duel ended.\n");
            break;
        }

        if (status == OCG_DUEL_STATUS_AWAITING) {
            uint32_t length = 0;
            void* message = OCG_DuelGetMessage(duel, &length);

            printf("Engine is awaiting a response.\n");

            if (message == nullptr || length == 0) {
                printf("ERROR: Awaiting state without a message.\n");
                OCG_DestroyDuel(duel);
                return 1;
            }

            dump_messages(message, length);

            printf("Stopping test at first response-required state.\n");
            break;
        }

        if (status == OCG_DUEL_STATUS_CONTINUE) {
            uint32_t length = 0;
            void* message = OCG_DuelGetMessage(duel, &length);

            if (message != nullptr && length > 0)
                dump_messages(message, length);
        }
    }

    OCG_DestroyDuel(duel);
    printf("\nDuel destroyed successfully.\n");

    return 0;
}