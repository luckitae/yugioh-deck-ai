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
static int script_reader(void* payload, OCG_Duel duel, const char* name) { (void)payload; (void)duel; (void)name; return 0; }
static void log_handler(void* payload, const char* string, int type) { (void)payload; (void)string; (void)type; }
static void card_reader_done(void* payload, OCG_CardData* data) { (void)payload; (void)data; }

int main() {
    int major = 0, minor = 0;
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
    if (duel != nullptr) {
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
   }

    if (duel != nullptr) {
        OCG_DestroyDuel(duel);
        printf("Duel destroyed successfully.\n");
    }
    return 0;
}
