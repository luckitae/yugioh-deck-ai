#include "protocol/bot_response.h"
#include "protocol/smoke_response.h"
#include "ocgapi_constants.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
int checks = 0;
void check(bool ok, const char* message) { ++checks; if(!ok) throw std::runtime_error(message); }
void put16(std::vector<uint8_t>& v, uint16_t x){v.push_back(x);v.push_back(x>>8);} 
void put32(std::vector<uint8_t>& v, uint32_t x){for(int i=0;i<4;++i)v.push_back(x>>(8*i));}
void put64(std::vector<uint8_t>& v, uint64_t x){for(int i=0;i<8;++i)v.push_back(x>>(8*i));}
void loc(std::vector<uint8_t>& v){v.push_back(0);v.push_back(LOCATION_HAND);put32(v,0);put32(v,0);} // loc_info = 10
DecodedMessage msg(std::vector<uint8_t>& v){return {v[0],v.data(),static_cast<uint32_t>(v.size())};}
uint32_t out32(const yda::BotResponse& r, size_t o=0){return yda::read_u32(r.bytes.data()+o);}

void test_idle(){
    std::vector<uint8_t> p{MSG_SELECT_IDLECMD,0};
    for(int list=0;list<6;++list){ put32(p,list==0?1:0); if(list==0){put32(p,123);p.push_back(0);p.push_back(LOCATION_HAND);put32(p,0);} }
    p.push_back(1);p.push_back(1);p.push_back(0);
    auto r=yda::first_legal_response(msg(p)); check(r.action=="normal_summon","idle action"); check(out32(r)==0,"idle command"); check(r.selected_code==123,"idle code");
}
void test_battle(){
    std::vector<uint8_t> p{MSG_SELECT_BATTLECMD,0}; put32(p,0);put32(p,1);put32(p,456);p.push_back(0);p.push_back(LOCATION_MZONE);p.push_back(0);p.push_back(1);p.push_back(1);p.push_back(1);
    auto r=yda::first_legal_response(msg(p)); check(r.action=="attack","battle action"); check(out32(r)==1,"battle command"); check(r.selected_code==456,"battle code");
}
void test_simple(){
    {std::vector<uint8_t> p{MSG_SELECT_YESNO,0};put64(p,1);auto r=yda::first_legal_response(msg(p));check(out32(r)==1,"yesno");}
    {std::vector<uint8_t> p{MSG_SELECT_EFFECTYN,1};put32(p,1);loc(p);put64(p,1);auto r=yda::first_legal_response(msg(p));check(out32(r)==1,"effectyn");}
    {std::vector<uint8_t> p{MSG_SELECT_OPTION,0,2};put64(p,11);put64(p,12);auto r=yda::first_legal_response(msg(p));check(out32(r)==0,"option");}
    {std::vector<uint8_t> p{MSG_SELECT_POSITION,0};put32(p,1);p.push_back(POS_FACEUP_ATTACK|POS_FACEUP_DEFENSE);auto r=yda::first_legal_response(msg(p));check(out32(r)==POS_FACEUP_ATTACK,"position");}
}
void test_chain_card_place(){
    {std::vector<uint8_t> p{MSG_SELECT_CHAIN,0,0,0};put32(p,0);put32(p,0);put32(p,0);auto r=yda::first_legal_response(msg(p));check(static_cast<int32_t>(out32(r))==-1,"chain pass");}
    {std::vector<uint8_t> p{MSG_SELECT_CARD,0,0};put32(p,1);put32(p,2);put32(p,2);for(uint32_t c:{10u,20u}){put32(p,c);loc(p);}auto r=yda::first_legal_response(msg(p));check(out32(r)==0 && out32(r,4)==1 && out32(r,8)==0,"card min");check(r.selected_code==10,"card code");}
    {std::vector<uint8_t> p{MSG_SELECT_PLACE,0,1};put32(p,0);auto r=yda::first_legal_response(msg(p));check(r.bytes.size()==3 && r.bytes[0]==0 && r.bytes[1]==LOCATION_MZONE && r.bytes[2]==0,"place");}
}
void test_tribute_counter_sum(){
    {std::vector<uint8_t> p{MSG_SELECT_TRIBUTE,0,0};put32(p,2);put32(p,2);put32(p,2);for(auto [c,val]:{std::pair<uint32_t,uint8_t>{11,1},{22,2}}){put32(p,c);p.push_back(0);p.push_back(LOCATION_MZONE);put32(p,0);p.push_back(val);}auto r=yda::first_legal_response(msg(p));check(out32(r)==0,"tribute encoding");check(out32(r,4)>=1,"tribute count");}
    {std::vector<uint8_t> p{MSG_SELECT_COUNTER,0};put16(p,1);put16(p,3);put32(p,2);for(auto [c,n]:{std::pair<uint32_t,uint16_t>{11,2},{22,2}}){put32(p,c);p.push_back(0);p.push_back(LOCATION_MZONE);p.push_back(0);put16(p,n);}auto r=yda::first_legal_response(msg(p));check(r.bytes.size()==4,"counter bytes");check(r.bytes[0]==2 && r.bytes[2]==1,"counter distribution");}
    {std::vector<uint8_t> p{MSG_SELECT_SUM,0,0};put32(p,5);put32(p,1);put32(p,1);put32(p,0);put32(p,1);put32(p,33);loc(p);put32(p,5);auto r=yda::first_legal_response(msg(p));check(out32(r)==0 && out32(r,4)==1 && out32(r,8)==0,"sum exact");}
}
void test_misc(){
    {std::vector<uint8_t> p{MSG_SELECT_UNSELECT_CARD,0,1,0};put32(p,1);put32(p,1);put32(p,1);put32(p,44);loc(p);put32(p,0);auto r=yda::first_legal_response(msg(p));check(static_cast<int32_t>(out32(r))==-1,"unselect finish");}
    {std::vector<uint8_t> p{MSG_SORT_CARD,0};put32(p,1);put32(p,1);p.push_back(0);put32(p,LOCATION_DECK);put32(p,0);auto r=yda::first_legal_response(msg(p));check(static_cast<int32_t>(out32(r))==-1,"sort keep");}
    {std::vector<uint8_t> p{MSG_ANNOUNCE_ATTRIB,0,2};put32(p,0b1011);auto r=yda::first_legal_response(msg(p));check(out32(r)==0b0011,"attribute bits");}
    {std::vector<uint8_t> p{MSG_ANNOUNCE_RACE,0,2};put64(p,0b1101);auto r=yda::first_legal_response(msg(p));check(r.bytes.size()==8 && yda::read_u32(r.bytes.data())==0b0101,"race bits");}
    {std::vector<uint8_t> p{MSG_ANNOUNCE_NUMBER,0,2};put64(p,3);put64(p,7);auto r=yda::first_legal_response(msg(p));check(out32(r)==0,"number");}
    {std::vector<uint8_t> p{MSG_ROCK_PAPER_SCISSORS,1};auto r=yda::first_legal_response(msg(p));check(out32(r)==2,"rps");}
}
void test_errors(){
    bool caught=false;try{std::vector<uint8_t> p{MSG_REQUEST_DECK,0};(void)yda::first_legal_response(msg(p));}catch(const yda::UnsupportedSelection&){caught=true;}check(caught,"unsupported request deck");
    caught=false;try{std::vector<uint8_t> p{MSG_SELECT_OPTION,0,0};(void)yda::first_legal_response(msg(p));}catch(const yda::ProtocolError&){caught=true;}check(caught,"bad option rejected");
}
}
int main(){try{test_idle();test_battle();test_simple();test_chain_card_place();test_tribute_counter_sum();test_misc();test_errors();std::cout<<"PHASE5-B UNIT PASS: "<<checks<<" checks\n";return 0;}catch(const std::exception& e){std::cerr<<"PHASE5-B UNIT FAIL: "<<e.what()<<"\n";return 1;}}
