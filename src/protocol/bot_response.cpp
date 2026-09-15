#include "bot_response.h"
#include "protocol/smoke_response.h"
#include "ocgapi_constants.h"
#include <algorithm>
#include <limits>
#include <map>
#include <stdexcept>
#include <tuple>
#include <utility>

namespace yda {
namespace {
constexpr uint32_t LIMIT = 4096;

void require(bool condition, const std::string& message) {
    if(!condition) throw ProtocolError(message);
}
uint16_t u16(const uint8_t* p) { return uint16_t(p[0]) | (uint16_t(p[1]) << 8); }
uint32_t u32(const uint8_t* p) { return read_u32(p); }
uint64_t u64(const uint8_t* p) {
    uint64_t v = 0;
    for(unsigned i = 0; i < 8; ++i) v |= uint64_t(p[i]) << (8 * i);
    return v;
}
void put16(std::vector<uint8_t>& out, uint16_t v) {
    out.push_back(static_cast<uint8_t>(v)); out.push_back(static_cast<uint8_t>(v >> 8));
}
void put32(std::vector<uint8_t>& out, uint32_t v) { append_u32(out, v); }
void put64(std::vector<uint8_t>& out, uint64_t v) {
    for(unsigned i = 0; i < 8; ++i) out.push_back(static_cast<uint8_t>(v >> (8 * i)));
}
void put_i32(std::vector<uint8_t>& out, int32_t v) { put32(out, static_cast<uint32_t>(v)); }
void index_list(std::vector<uint8_t>& out, const std::vector<uint32_t>& indices) {
    put_i32(out, 0); put32(out, static_cast<uint32_t>(indices.size()));
    for(uint32_t i : indices) put32(out, i);
}
void exact(uint32_t size, uint64_t expected, const char* label) {
    require(uint64_t(size) == expected, std::string(label) + ": malformed payload");
}

BotResponse base(const DecodedMessage& m) {
    require(m.payload && m.payload_size >= 2, "Selection: missing player");
    require(m.payload[0] == m.type && m.payload[1] <= 1, "Selection: invalid type/player");
    BotResponse r; r.prompt = m.type; r.player = m.payload[1]; return r;
}

std::vector<uint32_t> tribute_subset(const uint8_t* entries, uint32_t count, uint32_t min_value, uint32_t max_cards) {
    std::map<std::pair<uint32_t,uint32_t>, std::vector<uint32_t>> dp;
    dp[{0,0}] = {};
    for(uint32_t i = 0; i < count; ++i) {
        const uint32_t value = entries[i * 11 + 10];
        auto next = dp;
        for(const auto& [state, list] : dp) {
            if(state.first >= max_cards) continue;
            auto nl = list; nl.push_back(i);
            auto key = std::make_pair(state.first + 1, state.second + value);
            next.emplace(key, std::move(nl));
        }
        dp.swap(next);
    }
    for(const auto& [state, list] : dp)
        if(!list.empty() && state.first <= max_cards && state.second >= min_value) return list;
    throw UnsupportedSelection("TRIBUTE: no legal subset found");
}

std::vector<uint32_t> sum_subset(const std::vector<uint32_t>& must, const std::vector<uint32_t>& optional,
                                 uint32_t target, uint32_t min_count, uint32_t max_count, bool exact_mode) {
    const uint32_t n = static_cast<uint32_t>(optional.size());
    if(exact_mode) {
        // (selected optional count, reachable sum) -> first deterministic index list.
        std::map<std::pair<uint32_t,uint32_t>, std::vector<uint32_t>> states;
        states[{0,0}] = {};
        for(uint32_t op : must) {
            std::map<std::pair<uint32_t,uint32_t>, std::vector<uint32_t>> next;
            const uint32_t values[2] = {op & 0xffffu, op >> 16};
            for(const auto& [key, list] : states) {
                for(unsigned k = 0; k < 2; ++k) {
                    const uint32_t value = values[k];
                    if(k == 1 && value == 0) continue;
                    if(value <= target - key.second)
                        next.emplace(std::make_pair(key.first, key.second + value), list);
                }
            }
            states.swap(next);
        }
        for(uint32_t i = 0; i < n; ++i) {
            auto next = states; // skip candidate i
            const uint32_t values[2] = {optional[i] & 0xffffu, optional[i] >> 16};
            for(const auto& [key, list] : states) {
                if(key.first >= max_count) continue;
                for(unsigned k = 0; k < 2; ++k) {
                    const uint32_t value = values[k];
                    if(k == 1 && value == 0) continue;
                    if(value > target - key.second) continue;
                    auto nl = list; nl.push_back(i);
                    next.emplace(std::make_pair(key.first + 1, key.second + value), std::move(nl));
                }
            }
            states.swap(next);
            require(states.size() <= 200000, "SUM: deterministic DP state limit exceeded");
        }
        for(const auto& [key, list] : states)
            if(key.first >= min_count && key.first <= max_count && key.second == target) return list;
    } else {
        using Key = std::tuple<uint64_t,uint64_t,uint32_t,uint32_t>; // low, high, min-low, count
        auto add_param = [](uint64_t low, uint64_t high, uint32_t mn, uint32_t op) {
            const uint32_t a = op & 0xffffu, b = op >> 16;
            const uint32_t lo = (b && b < a) ? b : a, hi = std::max(a,b);
            return std::tuple<uint64_t,uint64_t,uint32_t>{low + lo, high + hi, std::min(mn, lo)};
        };
        uint64_t base_low = 0, base_high = 0; uint32_t base_mn = UINT32_MAX;
        for(uint32_t op : must) {
            auto [lo, hi, mn] = add_param(base_low, base_high, base_mn, op);
            base_low = lo; base_high = hi; base_mn = mn;
        }
        std::map<Key,std::vector<uint32_t>> states;
        states[{base_low,base_high,base_mn,0}] = {};
        auto valid = [target](const Key& key) {
            const auto low = std::get<0>(key), high = std::get<1>(key);
            const auto mn = std::get<2>(key);
            return mn != UINT32_MAX && high >= target && low >= mn && low - mn < target;
        };
        for(const auto& [key,list] : states) if(valid(key)) return list;
        for(uint32_t i = 0; i < n; ++i) {
            auto next = states;
            for(const auto& [key,list] : states) {
                auto [lo,hi,mn] = add_param(std::get<0>(key),std::get<1>(key),std::get<2>(key),optional[i]);
                auto nl=list; nl.push_back(i);
                next.emplace(Key{lo,hi,mn,std::get<3>(key)+1},std::move(nl));
            }
            states.swap(next);
            require(states.size() <= 200000, "SUM: deterministic DP state limit exceeded");
            for(const auto& [key,list] : states) if(valid(key)) return list;
        }
    }
    throw UnsupportedSelection("SUM: no legal deterministic subset found");
}

bool declarable(const CardRecord& card, const std::vector<uint64_t>& ops) {
    std::vector<int64_t> st; bool alias = false, token = false;
    auto unary = [&](auto f){ if(st.empty()) return false; st.back() = f(st.back()); return true; };
    auto binary = [&](auto f){ if(st.size() < 2) return false; int64_t rhs=st.back(); st.pop_back(); int64_t lhs=st.back(); st.back()=f(lhs,rhs); return true; };
    for(uint64_t op : ops) {
        switch(op) {
            case OPCODE_ADD: if(!binary([](auto a,auto b){return a+b;})) return false; break;
            case OPCODE_SUB: if(!binary([](auto a,auto b){return a-b;})) return false; break;
            case OPCODE_MUL: if(!binary([](auto a,auto b){return a*b;})) return false; break;
            case OPCODE_DIV: if(st.size()<2 || st.back()==0) return false; {auto b=st.back();st.pop_back();st.back()/=b;} break;
            case OPCODE_AND: if(!binary([](auto a,auto b){return int64_t(bool(a)&&bool(b));})) return false; break;
            case OPCODE_OR: if(!binary([](auto a,auto b){return int64_t(bool(a)||bool(b));})) return false; break;
            case OPCODE_NEG: if(!unary([](auto a){return -a;})) return false; break;
            case OPCODE_NOT: if(!unary([](auto a){return int64_t(!a);} )) return false; break;
            case OPCODE_BAND: if(!binary([](auto a,auto b){return a&b;})) return false; break;
            case OPCODE_BOR: if(!binary([](auto a,auto b){return a|b;})) return false; break;
            case OPCODE_BXOR: if(!binary([](auto a,auto b){return a^b;})) return false; break;
            case OPCODE_BNOT: if(!unary([](auto a){return ~a;})) return false; break;
            case OPCODE_LSHIFT: if(st.size()<2 || st.back()<0 || st.back()>=63) return false; {auto b=st.back();st.pop_back();st.back()<<=b;} break;
            case OPCODE_RSHIFT: if(st.size()<2 || st.back()<0 || st.back()>=63) return false; {auto b=st.back();st.pop_back();st.back()>>=b;} break;
            case OPCODE_ALLOW_ALIASES: alias = true; break;
            case OPCODE_ALLOW_TOKENS: token = true; break;
            case OPCODE_ISCODE: if(!unary([&](auto a){return int64_t(card.data.code == uint32_t(a));})) return false; break;
            case OPCODE_ISTYPE: if(!unary([&](auto a){return int64_t(card.data.type & uint32_t(a));})) return false; break;
            case OPCODE_ISRACE: if(!unary([&](auto a){return int64_t(card.data.race & uint64_t(a));})) return false; break;
            case OPCODE_ISATTRIBUTE: if(!unary([&](auto a){return int64_t(card.data.attribute & uint32_t(a));})) return false; break;
            case OPCODE_GETCODE: st.push_back(card.data.code); break;
            case OPCODE_GETTYPE: st.push_back(card.data.type); break;
            case OPCODE_GETRACE: st.push_back(static_cast<int64_t>(card.data.race)); break;
            case OPCODE_GETATTRIBUTE: st.push_back(card.data.attribute); break;
            case OPCODE_ISSETCARD: {
                if(st.empty()) return false; uint16_t sc=static_cast<uint16_t>(st.back()); st.pop_back();
                uint16_t type=sc&0xfff, subtype=sc&0xf000; bool ok=false;
                for(uint16_t own: card.setcodes) if((own&0xfff)==type && (own&0xf000&subtype)==subtype) {ok=true;break;}
                st.push_back(ok); break;
            }
            default: st.push_back(static_cast<int64_t>(op)); break;
        }
    }
    if(st.size()!=1 || st.back()==0) return false;
    const bool special = card.data.code == 78734254u || card.data.code == 13857930u;
    return special || ((alias || !card.data.alias) && (token || ((card.data.type & (TYPE_MONSTER | TYPE_TOKEN)) != (TYPE_MONSTER | TYPE_TOKEN))));
}
}

bool is_bot_selection(uint32_t type) { return is_selection(type); }

BotResponse first_legal_response(const DecodedMessage& m, const CardDatabase* db) {
    BotResponse r = base(m); const uint8_t* p = m.payload; const uint32_t size = m.payload_size;
    if(m.type == MSG_SELECT_IDLECMD) {
        IdleCmdMessage idle{}; require(decode_idle_cmd(&m,&idle)!=0, "IDLE: invalid payload");
        const uint32_t counts[] = {idle.summonable_count,idle.spsummonable_count,idle.repositionable_count,idle.msetable_count,idle.ssetable_count,idle.activate_count};
        const uint32_t widths[] = {10,10,7,10,10,19}; uint32_t offsets[6]; uint32_t off=2;
        for(unsigned i=0;i<6;++i){ require(counts[i]<=LIMIT,"IDLE: too many candidates"); off+=4; offsets[i]=off; off+=counts[i]*widths[i]; }
        auto choose=[&](unsigned list,uint32_t type,const char* action){ if(!counts[list]) return false; r.selected_index=0; r.selected_code=u32(p+offsets[list]); r.action=action; put32(r.bytes,type); return true; };
        // Prefer proactive actions, then progress the turn.
        if(choose(5,(0u<<16)|5u,"activate") || choose(1,(0u<<16)|1u,"special_summon") || choose(0,0u,"normal_summon") ||
           choose(2,(0u<<16)|2u,"reposition") || choose(4,(0u<<16)|4u,"set_spell_trap") || choose(3,(0u<<16)|3u,"set_monster")) return r;
        if(idle.to_bp){ r.action="to_battle"; put32(r.bytes,6); return r; }
        require(idle.to_ep,"IDLE: no legal progress action"); r.action="to_end"; put32(r.bytes,7); return r;
    }
    if(m.type == MSG_SELECT_BATTLECMD) {
        require(size>=8,"BATTLE: short payload"); uint32_t off=2, ac=u32(p+off); off+=4; require(ac<=LIMIT && uint64_t(off)+uint64_t(ac)*19+4<=size,"BATTLE: bad activatable list");
        uint32_t actoff=off; off+=ac*19; uint32_t attacks=u32(p+off); off+=4; require(attacks<=LIMIT && uint64_t(off)+uint64_t(attacks)*8+2==size,"BATTLE: bad attack list");
        if(ac){ r.selected_index=0;r.selected_code=u32(p+actoff);r.action="battle_activate";put32(r.bytes,0);return r; }
        if(attacks){ r.selected_index=0;r.selected_code=u32(p+off);r.action="attack";put32(r.bytes,1);return r; }
        const uint8_t to_m2=p[size-2], to_ep=p[size-1]; require(to_m2<=1&&to_ep<=1,"BATTLE: bad flags");
        if(to_m2){r.action="to_main2";put32(r.bytes,2);return r;} require(to_ep,"BATTLE: no legal progress action");r.action="to_end";put32(r.bytes,3);return r;
    }
    if(m.type == MSG_SELECT_EFFECTYN || m.type == MSG_SELECT_YESNO) { r.action="yes"; put32(r.bytes,1); return r; }
    if(m.type == MSG_SELECT_OPTION) { require(size>=3 && p[2]>0 && uint64_t(3)+uint64_t(p[2])*8==size,"OPTION: malformed"); r.action="option_0";r.selected_index=0;put32(r.bytes,0);return r; }
    if(m.type == MSG_SELECT_CHAIN) { require(size>=16,"CHAIN: short"); uint32_t count=u32(p+12); require(count<=LIMIT && uint64_t(16)+uint64_t(count)*23==size,"CHAIN: malformed"); bool forced=p[3]!=0; if(count && forced){r.action="chain_0";r.selected_index=0;r.selected_code=u32(p+16);put32(r.bytes,0);} else if(count){r.action="chain_0";r.selected_index=0;r.selected_code=u32(p+16);put32(r.bytes,0);} else {require(!forced,"CHAIN: forced empty");r.action="chain_pass";put_i32(r.bytes,-1);} return r; }
    if(m.type == MSG_SELECT_CARD) { require(size>=15,"CARD: short"); uint32_t min=u32(p+3),max=u32(p+7),count=u32(p+11); require(count<=LIMIT && min<=max && max<=count && uint64_t(15)+uint64_t(count)*14==size,"CARD: malformed"); std::vector<uint32_t> ids; for(uint32_t i=0;i<min;++i) ids.push_back(i); r.action="select_card_min"; if(min){r.selected_index=0;r.selected_code=u32(p+15);} index_list(r.bytes,ids); return r; }
    if(m.type == MSG_SELECT_UNSELECT_CARD) { require(size>=20,"UNSELECT: short"); bool finish=p[2],cancel=p[3]; uint32_t sc=u32(p+12); require(sc<=LIMIT,"UNSELECT: too many select cards"); uint64_t off=16+uint64_t(sc)*14; require(off+4<=size,"UNSELECT: truncated"); uint32_t uc=u32(p+off); require(uc<=LIMIT && off+4+uint64_t(uc)*14==size,"UNSELECT: malformed"); if(finish||cancel){r.action="finish_selection";put_i32(r.bytes,-1);} else {require(sc+uc>0,"UNSELECT: no candidate");r.action="toggle_card_0";put_i32(r.bytes,1);put32(r.bytes,0);} return r; }
    if(m.type == MSG_SELECT_PLACE || m.type == MSG_SELECT_DISFIELD) { exact(size,7,"PLACE"); uint8_t count=p[2]; require(count>0 && count<=30,"PLACE: invalid count"); uint32_t flag=u32(p+3); for(unsigned rel=0;rel<2 && r.bytes.size()<size_t(count)*3;++rel) for(unsigned zone=0;zone<2 && r.bytes.size()<size_t(count)*3;++zone){unsigned n=zone?8:7;for(unsigned seq=0;seq<n && r.bytes.size()<size_t(count)*3;++seq){unsigned bit=rel*16+zone*8+seq;if(!(flag&(uint32_t(1)<<bit))){r.bytes.push_back(r.player^rel);r.bytes.push_back(zone?LOCATION_SZONE:LOCATION_MZONE);r.bytes.push_back(seq);flag|=uint32_t(1)<<bit;}}} require(r.bytes.size()==size_t(count)*3,"PLACE: not enough zones");r.action=m.type==MSG_SELECT_DISFIELD?"disable_place":"select_place";return r; }
    if(m.type == MSG_SELECT_POSITION) { exact(size,7,"POSITION"); uint8_t pos=p[6]&0xf; const uint8_t order[]={POS_FACEUP_ATTACK,POS_FACEUP_DEFENSE,POS_FACEDOWN_DEFENSE,POS_FACEDOWN_ATTACK}; for(uint8_t v:order) if(pos&v){r.action="select_position";put32(r.bytes,v);return r;} throw ProtocolError("POSITION: no legal bit"); }
    if(m.type == MSG_SELECT_TRIBUTE) { require(size>=15,"TRIBUTE: short"); uint32_t min=u32(p+3),max=u32(p+7),count=u32(p+11); require(count<=LIMIT && uint64_t(15)+uint64_t(count)*11==size,"TRIBUTE: malformed"); auto ids=tribute_subset(p+15,count,min,max); r.action="select_tribute"; if(!ids.empty()){r.selected_index=ids[0];r.selected_code=u32(p+15+ids[0]*11);} index_list(r.bytes,ids); return r; }
    if(m.type == MSG_SELECT_COUNTER) { require(size>=10,"COUNTER: short"); uint32_t need=u16(p+4),count=u32(p+6); require(count<=LIMIT && uint64_t(10)+uint64_t(count)*9==size,"COUNTER: malformed"); uint32_t left=need; for(uint32_t i=0;i<count;++i){uint16_t have=u16(p+10+i*9+7),take=static_cast<uint16_t>(std::min<uint32_t>(have,left));put16(r.bytes,take);left-=take;} require(left==0,"COUNTER: insufficient counters");r.action="select_counter";return r; }
    if(m.type == MSG_SELECT_SUM) { require(size>=19,"SUM: short"); bool exact_mode=p[2]==0; require(p[2]<=1,"SUM: bad mode"); uint32_t target=u32(p+3),min=u32(p+7),max=u32(p+11),mc=u32(p+15); require(mc<=LIMIT,"SUM: too many mandatory cards"); uint64_t off=19+uint64_t(mc)*18; require(off+4<=size,"SUM: truncated mandatory"); std::vector<uint32_t> must; for(uint32_t i=0;i<mc;++i) must.push_back(u32(p+19+i*18+14)); uint32_t oc=u32(p+off); off+=4; require(oc<=LIMIT && off+uint64_t(oc)*18==size,"SUM: malformed optional"); std::vector<uint32_t> opt; for(uint32_t i=0;i<oc;++i) opt.push_back(u32(p+off+i*18+14)); auto ids=sum_subset(must,opt,target,min,max,exact_mode);r.action="select_sum";if(!ids.empty()){r.selected_index=ids[0];r.selected_code=u32(p+off+ids[0]*18);}index_list(r.bytes,ids);return r; }
    if(m.type == MSG_SORT_CARD || m.type == MSG_SORT_CHAIN) { require(size>=6,"SORT: short"); uint32_t count=u32(p+2); require(count<=255 && uint64_t(6)+uint64_t(count)*13==size,"SORT: malformed");r.action="keep_order";put_i32(r.bytes,-1);return r; }
    if(m.type == MSG_ANNOUNCE_RACE) { exact(size,11,"RACE"); uint8_t count=p[2]; uint64_t avail=u64(p+3),sel=0; for(unsigned bit=0;bit<64&&count;++bit)if(avail&(uint64_t(1)<<bit)){sel|=uint64_t(1)<<bit;--count;}require(count==0,"RACE: insufficient bits");r.action="announce_race";put64(r.bytes,sel);return r; }
    if(m.type == MSG_ANNOUNCE_ATTRIB) { exact(size,7,"ATTRIB"); uint8_t count=p[2]; uint32_t avail=u32(p+3),sel=0; for(unsigned bit=0;bit<32&&count;++bit)if(avail&(uint32_t(1)<<bit)){sel|=uint32_t(1)<<bit;--count;}require(count==0,"ATTRIB: insufficient bits");r.action="announce_attribute";put32(r.bytes,sel);return r; }
    if(m.type == MSG_ANNOUNCE_NUMBER) { require(size>=3 && p[2]>0 && uint64_t(3)+uint64_t(p[2])*8==size,"NUMBER: malformed");r.action="announce_number_0";r.selected_index=0;put32(r.bytes,0);return r; }
    if(m.type == MSG_ROCK_PAPER_SCISSORS) { exact(size,2,"RPS"); r.action="rps"; put32(r.bytes,r.player?2:1); return r; }
    if(m.type == MSG_ANNOUNCE_CARD) { require(size>=3 && p[2]>0 && uint64_t(3)+uint64_t(p[2])*8==size,"ANNOUNCE_CARD: malformed"); require(db,"ANNOUNCE_CARD: database required"); std::vector<uint64_t> ops; for(uint32_t i=0;i<p[2];++i) ops.push_back(u64(p+3+i*8)); for(const auto& [code,card]:db->records()) if(declarable(card,ops)){r.action="announce_card";r.selected_code=code;put32(r.bytes,code);return r;} throw UnsupportedSelection("ANNOUNCE_CARD: no declarable database card found"); }
    throw UnsupportedSelection("Unsupported selection: " + std::to_string(m.type) + " " + message_name(m.type));
}
}
