// One kernel call per activation, with fresh streams after every error.
#include "maxaffine.hpp"
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include <cstdint>

struct Beat { uint32_t value; int last; };
int main(int argc,char** argv) {
    if (argc!=4) return 2;
    const std::string vectors=argv[1], evidence=argv[2], stage=argv[3];
    std::ifstream names(vectors+"/scenarios.txt");
    std::ofstream rows(evidence+"/"+stage+"_checks.csv");
    std::ofstream raw(evidence+"/"+stage+"_words.csv");
    rows<<"scenario,result,halted,error,tx_id,output_words,unread_words\n";
    raw<<"scenario,index,data,last,keep,strb\n";
    std::string name;
    int failures=0, runs=0;
    while(names>>name) {
        std::ifstream f(vectors+"/"+name+".txt");
        int ni,no,consumed,eh,ee,et;
        if (!(f>>ni>>no>>consumed>>eh>>ee>>et)) return 2;
        hls::stream<axis_t> input,output;
        for(int i=0;i<ni;++i) {
            uint32_t v; int last;
            f>>std::hex>>v>>std::dec>>last;
            axis_t w; w.data=v; w.last=last; w.keep=15; w.strb=15;
            input.write(w);
        }
        std::vector<Beat> expected;
        for(int i=0;i<no;++i) {
            uint32_t v; int last;
            f>>std::hex>>v>>std::dec>>last;
            expected.push_back({v,last});
        }
        // Poison output status so each call must really clear it.
        ap_uint<1> halted=1; ap_uint<8> error=255; ap_uint<16> tx_id=65535;
        maxaffine(input,output,halted,error,tx_id);
        bool pass=int(halted)==eh && int(error)==ee && int(tx_id)==et;
        int count=0;
        while(!output.empty()) {
            axis_t w=output.read();
            uint32_t value=w.data.to_uint();
            raw<<name<<','<<count<<','<<std::hex<<value<<std::dec<<','<<int(w.last)<<','<<int(w.keep)<<','<<int(w.strb)<<'\n';
            if(count>=no || value!=expected[count].value || int(w.last)!=expected[count].last || int(w.keep)!=15 || int(w.strb)!=15) pass=false;
            ++count;
        }
        if(count!=no) pass=false;
        int unread=0;
        while(!input.empty()) { input.read(); ++unread; }
        // RTL input consumption is checked from physical handshakes in the VCD:
        // the co-simulation C wrapper may already have serialized all input words.
        if(stage=="csim" && unread!=ni-consumed) pass=false;
        rows<<name<<','<<(pass?"PASS":"FAIL")<<','<<int(halted)<<','<<int(error)<<','<<int(tx_id)<<','<<count<<','<<unread<<'\n';
        std::cout<<"SCENARIO "<<name<<' '<<(pass?"PASS":"FAIL")<<" status="<<int(halted)<<','<<int(error)<<','<<int(tx_id)<<" output="<<count<<" unread="<<unread<<std::endl;
        if(!pass) ++failures;
        ++runs;
    }
    if(runs==0) return 2;
    std::cout<<"SUMMARY activations="<<runs<<" failures="<<failures<<std::endl;
    return failures ? 1 : 0;
}
