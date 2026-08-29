#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <stdexcept>

namespace bg1xg {
using Side = std::array<unsigned int,25>; // BG1: own points 1..24, bar at 24
struct Board { Side side0{}, side1{}; };
using XGState = std::array<std::int8_t,26>;

XGState to_xg_state(const Board& b) {
  XGState out{};
  auto checked=[](unsigned n)->std::int8_t {
    if(n>15) throw std::runtime_error("checker count >15");
    return static_cast<std::int8_t>(n);
  };

  // side0 is XG-positive. Own point p maps to physical/XG slot 25-p.
  out[0]=checked(b.side0[24]); // side0 bar
  for(int p=1;p<=24;++p) {
    const auto n=checked(b.side0[static_cast<std::size_t>(p-1)]);
    const int x=25-p;
    if(n && out[static_cast<std::size_t>(x)]!=0) throw std::runtime_error("overlap in BG1 board");
    if(n) out[static_cast<std::size_t>(x)]=n;
  }

  // side1 is XG-negative. Its own point p maps directly to XG slot p.
  for(int p=1;p<=24;++p) {
    const auto n=checked(b.side1[static_cast<std::size_t>(p-1)]);
    const int x=p;
    if(n && out[static_cast<std::size_t>(x)]!=0) throw std::runtime_error("overlap in BG1 board");
    if(n) out[static_cast<std::size_t>(x)]=static_cast<std::int8_t>(-n);
  }
  out[25]=static_cast<std::int8_t>(-checked(b.side1[24])); // side1 bar
  return out;
}

Board standard_start() {
  Board b;
  for(auto* s:{&b.side0,&b.side1}) {
    (*s)[23]=2; // 24-point
    (*s)[12]=5; // 13-point
    (*s)[7]=3;  // 8-point
    (*s)[5]=5;  // 6-point
  }
  return b;
}

void selftest() {
  const XGState expected={0,2,0,0,0,0,-5,0,-3,0,0,0,5,-5,0,0,0,3,0,5,0,0,0,0,-2,0};
  assert(to_xg_state(standard_start())==expected);

  Board bar;
  bar.side0[24]=1;
  bar.side1[24]=2;
  const auto x=to_xg_state(bar);
  assert(x[0]==1 && x[25]==-2);

  std::cout << "R43_BG1_XG_STATE_ADAPTER=PASS\n";
}
} // namespace bg1xg

int main(){ bg1xg::selftest(); }
