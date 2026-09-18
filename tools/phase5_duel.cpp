#include "data/card_database.h"
#include "data/deck_loader.h"
#include "data/script_loader.h"
#include "protocol/bot_response.h"
#include "protocol/smoke_response.h"
#include "ocgapi.h"
#include "ocgapi_constants.h"
#include <algorithm>
#include <array>
#include <charconv>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>

namespace {
struct Arguments {
    std::filesystem::path db, scripts, deck0, deck1, result, trace;
    std::string run_id, attempt_id;
    uint64_t seed = 1;
    uint64_t max_calls = 200000;
    std::array<yda::RequiredMain,2> required_main, required_extra;
};
struct Result {
    std::string status = "input_error", error;
    int winner = -1, reason = -1;
    uint64_t calls = 0, turns = 0, selections = 0, trace_events = 0;
    uint64_t summons = 0, special_summons = 0, attacks = 0, chains = 0, chains_solved = 0;
    uint64_t damage_events = 0, damage_total = 0, scripts = 0, optional_scripts = 0, engine_errors = 0, card_reads = 0;
    std::array<size_t,2> main{}, extra{}, side{};
    std::map<std::string,uint64_t> actions;
    std::map<std::string,uint64_t> prompts;
};
struct DuelGuard { OCG_Duel value=nullptr; ~DuelGuard(){ if(value) OCG_DestroyDuel(value); } };

uint64_t number(const std::string& s) {
    uint64_t v=0; auto p=std::from_chars(s.data(),s.data()+s.size(),v);
    if(p.ec!=std::errc() || p.ptr!=s.data()+s.size()) throw std::runtime_error("Invalid unsigned integer: "+s);
    return v;
}
void required_value(const std::string& s, yda::RequiredMain& out) {
    const auto at=s.find('='); if(at==std::string::npos) throw std::runtime_error("required format: code=count");
    uint64_t code=number(s.substr(0,at)), count=number(s.substr(at+1));
    if(code==0 || code>UINT32_MAX || count==0 || count>3) throw std::runtime_error("invalid required card/count");
    if(!out.emplace(static_cast<uint32_t>(code),static_cast<unsigned>(count)).second) throw std::runtime_error("repeated required card");
}
bool valid_id(const std::string& value) {
    if(value.empty() || value.size() > 128)
        return false;
    for(unsigned char ch : value) {
        if(!((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
             (ch >= '0' && ch <= '9') || ch == '.' || ch == '_' || ch == '-'))
            return false;
    }
    return true;
}
void parse(int argc,char** argv,Arguments& a) {
    for(int i=1;i<argc;++i){ std::string k=argv[i]; if(++i>=argc) throw std::runtime_error("Missing value for "+k); std::string v=argv[i];
        if(k=="--db") a.db=v; else if(k=="--scripts") a.scripts=v; else if(k=="--deck0") a.deck0=v; else if(k=="--deck1") a.deck1=v;
        else if(k=="--result") a.result=v; else if(k=="--trace") a.trace=v; else if(k=="--run-id") a.run_id=v; else if(k=="--attempt-id") a.attempt_id=v;
        else if(k=="--seed") a.seed=number(v); else if(k=="--max-calls") a.max_calls=number(v);
        else if(k=="--required-main0") required_value(v,a.required_main[0]); else if(k=="--required-main1") required_value(v,a.required_main[1]);
        else if(k=="--required-extra0") required_value(v,a.required_extra[0]); else if(k=="--required-extra1") required_value(v,a.required_extra[1]);
        else if(k=="--policy") { if(v!="first-legal-v1") throw std::runtime_error("Only --policy first-legal-v1 is supported"); }
        else throw std::runtime_error("Unknown argument: "+k);
    }
    if(a.db.empty()||a.scripts.empty()||a.deck0.empty()||a.deck1.empty()||a.result.empty()||a.trace.empty())
        throw std::runtime_error("Required: --db --scripts --deck0 --deck1 --result --trace");
    if(!valid_id(a.run_id) || !valid_id(a.attempt_id))
        throw std::runtime_error("Required: valid --run-id and --attempt-id");
    if(a.max_calls==0 || a.max_calls>1000000) throw std::runtime_error("max-calls must be 1..1000000");
}
std::string js(const std::string& s){ std::string o="\""; for(unsigned char c:s){if(c=='\"'||c=='\\'){o+='\\';o+=char(c);}else if(c<32){char b[7];std::snprintf(b,sizeof(b),"\\u%04x",unsigned(c));o+=b;}else o+=char(c);} return o+'\"'; }
void map_json(std::ofstream& f,const std::map<std::string,uint64_t>& m){ f<<'{'; bool first=true; for(const auto& [k,v]:m){if(!first)f<<',';first=false;f<<js(k)<<':'<<v;} f<<'}'; }

class Trace {
public:
    explicit Trace(const std::filesystem::path& p){ if(!p.empty()){ if(!p.parent_path().empty())std::filesystem::create_directories(p.parent_path()); file_.open(p); if(!file_)throw std::runtime_error("Cannot open trace file"); } }
    void selection(uint64_t seq,const yda::BotResponse& r){ if(!file_)return; file_<<"{\"seq\":"<<seq<<",\"kind\":\"selection\",\"player\":"<<unsigned(r.player)<<",\"prompt\":"<<r.prompt<<",\"prompt_name\":"<<js(message_name(r.prompt))<<",\"action\":"<<js(r.action)<<",\"selected_code\":"<<r.selected_code<<",\"selected_index\":"; if(r.selected_index==UINT32_MAX)file_<<"null";else file_<<r.selected_index; file_<<"}\n"; }
    void event(uint64_t seq,const char* kind,int player=-1,uint32_t value=0){ if(!file_)return; file_<<"{\"seq\":"<<seq<<",\"kind\":"<<js(kind); if(player>=0)file_<<",\"player\":"<<player; if(value)file_<<",\"value\":"<<value; file_<<"}\n"; }
private: std::ofstream file_;
};

void write_result(const Arguments& a,const Result& r){ if(!a.result.parent_path().empty())std::filesystem::create_directories(a.result.parent_path()); std::ofstream f(a.result); if(!f)throw std::runtime_error("Cannot write result");
    f<<"{\n\"schema\":2,\n\"result_type\":\"duel\",\n\"runner\":\"phase5b-duel-runner-v2\",\n\"engine_api\":\"11.0\",\n\"run_id\":"<<js(a.run_id)<<",\n\"attempt_id\":"<<js(a.attempt_id)<<",\n\"completed\":"<<(r.status=="finished"?"true":"false")<<",\n\"policy\":\"first-legal-v1\",\n\"seed\":"<<a.seed<<",\n\"first_player\":0,\n\"status\":"<<js(r.status)<<",\n\"error\":"<<js(r.error)<<",\n\"winner\":"<<(r.winner<0?"null":std::to_string(r.winner))<<",\n\"reason\":"<<(r.reason<0?"null":std::to_string(r.reason))<<",\n";
    f<<"\"process_calls\":"<<r.calls<<",\n\"turns\":"<<r.turns<<",\n\"selections\":"<<r.selections<<",\n\"trace_events\":"<<r.trace_events<<",\n\"summons\":"<<r.summons<<",\n\"special_summons\":"<<r.special_summons<<",\n\"attacks\":"<<r.attacks<<",\n\"chains\":"<<r.chains<<",\n\"chains_solved\":"<<r.chains_solved<<",\n\"damage_events\":"<<r.damage_events<<",\n\"damage_total\":"<<r.damage_total<<",\n";
    f<<"\"scripts_loaded\":"<<r.scripts<<",\n\"optional_scripts_missing\":"<<r.optional_scripts<<",\n\"engine_errors\":"<<r.engine_errors<<",\n\"card_reads\":"<<r.card_reads<<",\n\"main\":["<<r.main[0]<<','<<r.main[1]<<"],\n\"extra\":["<<r.extra[0]<<','<<r.extra[1]<<"],\n\"side\":["<<r.side[0]<<','<<r.side[1]<<"],\n\"deck_files\":["<<js(a.deck0.generic_string())<<','<<js(a.deck1.generic_string())<<"],\n\"actions\":"; map_json(f,r.actions); f<<",\n\"prompts\":"; map_json(f,r.prompts); f<<",\n\"trace_file\":"<<(a.trace.empty()?"null":js(a.trace.generic_string()))<<"\n}\n";
}

void validate_required_extra(const yda::Deck& deck,const yda::CardDatabase& db,const yda::RequiredMain& required){
    for(const auto& [code,count]:required){
        if(count==0||count>3||!db.find(code)) throw std::runtime_error("Deck: invalid required Extra card setting");
        const auto actual=std::count(deck.extra.begin(),deck.extra.end(),code);
        if(static_cast<unsigned>(actual)<count) throw std::runtime_error("Deck: required Extra card missing: "+std::to_string(code));
    }
}

void run(const Arguments& a,Result& r){
    yda::CardDatabase db(a.db); yda::Deck decks[]={yda::load_ydk(a.deck0),yda::load_ydk(a.deck1)};
    for(unsigned p=0;p<2;++p){ yda::validate_deck(decks[p],db,a.required_main[p]); validate_required_extra(decks[p],db,a.required_extra[p]); }
    for(unsigned p=0;p<2;++p){r.main[p]=decks[p].main.size();r.extra[p]=decks[p].extra.size();r.side[p]=decks[p].side.size();}
    int major=0,minor=0; OCG_GetVersion(&major,&minor); if(major!=11||minor!=0)throw std::runtime_error("Expected OCGCore API 11.0");
    yda::CardReaderContext reader{db}; yda::ScriptLoader scripts(a.scripts,db); DuelGuard duel; OCG_DuelOptions opt{}; opt.seed[0]=a.seed;opt.seed[1]=0x9e3779b97f4a7c15ULL;opt.seed[2]=0xd1b54a32d192ed03ULL;opt.seed[3]=0x94d049bb133111ebULL;opt.flags=DUEL_MODE_MR5; opt.team1={8000,5,1};opt.team2={8000,5,1}; opt.cardReader=yda::CardReaderContext::read;opt.payload1=&reader;opt.cardReaderDone=yda::CardReaderContext::release;opt.payload4=&reader;opt.scriptReader=yda::ScriptLoader::read;opt.payload2=&scripts;opt.logHandler=yda::ScriptLoader::log;opt.payload3=&scripts;
    auto resources=[&](){r.scripts=scripts.loaded_count();r.optional_scripts=scripts.optional_missing;r.engine_errors=scripts.engine_errors;r.card_reads=reader.reads;if(reader.failed||scripts.failed()){r.status="resource_error";throw std::runtime_error(reader.failed?"missing DB card "+std::to_string(reader.missing_code):scripts.error());}};
    if(OCG_CreateDuel(&duel.value,&opt)!=OCG_DUEL_CREATION_SUCCESS||!duel.value)throw std::runtime_error("OCG_CreateDuel failed"); resources(); scripts.bootstrap(duel.value);resources();
    for(uint8_t player=0;player<2;++player){const std::vector<uint32_t>* sections[]={&decks[player].main,&decks[player].extra};for(unsigned s=0;s<2;++s)for(uint32_t code:*sections[s]){OCG_NewCardInfo card{};card.team=player;card.duelist=0;card.code=code;card.con=player;card.loc=s?LOCATION_EXTRA:LOCATION_DECK;card.pos=POS_FACEDOWN_DEFENSE;OCG_DuelNewCard(duel.value,&card);resources();}}
    OCG_StartDuel(duel.value); resources(); Trace trace(a.trace); std::optional<yda::BotResponse> pending; r.status="protocol_error"; uint64_t seq=0;
    for(uint64_t i=0;i<a.max_calls;++i){int st=OCG_DuelProcess(duel.value);++r.calls;resources();uint32_t length=0;const auto* bytes=static_cast<const uint8_t*>(OCG_DuelGetMessage(duel.value,&length));if(length&&!bytes)throw yda::ProtocolError("null message buffer");uint32_t off=0;
        while(off<length){DecodedMessage m{};if(!decode_next_message(bytes,length,&off,&m))throw yda::ProtocolError("malformed message frame");++seq;const uint8_t* p=m.payload;
            if(m.type==MSG_RETRY)throw yda::ProtocolError("OCGCore rejected bot response (MSG_RETRY)");
            if(m.type==MSG_WIN){if(m.payload_size!=3||p[1]>2||r.winner!=-1||pending)throw yda::ProtocolError("malformed/duplicate WIN");r.winner=p[1];r.reason=p[2];trace.event(seq,"win",r.winner,r.reason);++r.trace_events;}
            else if(yda::is_bot_selection(m.type)){if(pending||r.winner!=-1)throw yda::ProtocolError("multiple pending selections");pending=yda::first_legal_response(m,&db);++r.selections;++r.actions[pending->action];++r.prompts[message_name(m.type)];trace.selection(seq,*pending);++r.trace_events;}
            else if(m.type==MSG_NEW_TURN){if(m.payload_size!=2||p[1]>1)throw yda::ProtocolError("bad NEW_TURN");++r.turns;trace.event(seq,"turn",p[1]);++r.trace_events;}
            else if(m.type==MSG_SUMMONED){++r.summons;trace.event(seq,"summoned");++r.trace_events;}
            else if(m.type==MSG_SPSUMMONED){++r.special_summons;trace.event(seq,"special_summoned");++r.trace_events;}
            else if(m.type==MSG_ATTACK){++r.attacks;trace.event(seq,"attack");++r.trace_events;}
            else if(m.type==MSG_CHAINING){++r.chains;trace.event(seq,"chaining");++r.trace_events;}
            else if(m.type==MSG_CHAIN_SOLVED){++r.chains_solved;}
            else if(m.type==MSG_DAMAGE){if(m.payload_size!=6||p[1]>1)throw yda::ProtocolError("bad DAMAGE");uint32_t amount=yda::read_u32(p+2);++r.damage_events;r.damage_total+=amount;trace.event(seq,"damage",p[1],amount);++r.trace_events;}
        }
        if(st!=OCG_DUEL_STATUS_END&&st!=OCG_DUEL_STATUS_AWAITING&&st!=OCG_DUEL_STATUS_CONTINUE)throw yda::ProtocolError("unknown process status");
        if(r.winner!=-1){r.status="finished";return;}
        if(st==OCG_DUEL_STATUS_END){r.status="no_result";throw std::runtime_error("END without MSG_WIN");}
        if(st==OCG_DUEL_STATUS_AWAITING){if(!pending)throw yda::UnsupportedSelection("AWAITING without supported response");OCG_DuelSetResponse(duel.value,pending->bytes.data(),static_cast<uint32_t>(pending->bytes.size()));pending.reset();}
    }
    r.status="limit_exceeded";throw std::runtime_error("process call limit exceeded");
}
}

int main(int argc,char** argv){Arguments a;Result r;try{parse(argc,argv,a);run(a,r);}catch(const yda::UnsupportedSelection& e){r.status="unsupported_selection";r.error=e.what();}catch(const yda::ProtocolError& e){r.status="protocol_error";r.error=e.what();}catch(const std::exception& e){r.error=e.what();}bool ok=r.status=="finished";if(!ok){r.winner=-1;r.reason=-1;std::cerr<<"PHASE5-B DUEL FAIL ["<<r.status<<"] "<<r.error<<'\n';}try{write_result(a,r);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}if(ok)std::cout<<"PHASE5-B DUEL PASS: winner="<<r.winner<<" reason="<<r.reason<<" turns="<<r.turns<<" selections="<<r.selections<<"\n";return ok?0:1;}
