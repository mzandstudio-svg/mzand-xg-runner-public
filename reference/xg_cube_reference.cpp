#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <utility>

namespace xgref {
using State = std::array<std::int8_t,26>;
using Side = std::array<int,25>;

constexpr float kEffDefaultF = 0.705f;
constexpr float kEffClass7F = 0.85f;
constexpr float kClass3TargetF = 0.72f;
constexpr float kClass3BaseF = 0.5f;
constexpr float kClass3TopF = 0.75f;
constexpr double kRaceMax = 0x1.c3c3c3c3cb86ap-1;

struct Features {
  int total=0, pip=0, back=-1;
};

std::pair<Side,Side> canonical(const State& s) {
  Side a{}, b{};
  for(int d=0; d<26; ++d) {
    const int v=s[static_cast<std::size_t>(d)];
    if(v>0) {
      const int j=d-1;
      if(j>=0 && j<25) a[static_cast<std::size_t>(j)]=v;
    } else {
      const int j=24-d;
      if(j>=0 && j<25) b[static_cast<std::size_t>(j)]=-v;
    }
  }
  return {a,b};
}

Features features(const Side& a) {
  Features f;
  for(int i=0;i<25;++i) if(a[static_cast<std::size_t>(i)]!=0) {
    f.back=i;
    f.total+=a[static_cast<std::size_t>(i)];
    f.pip+=i*a[static_cast<std::size_t>(i)];
  }
  return f;
}

std::uint64_t choose(int n,int r) {
  if(r<0 || r>n) return 0;
  r=std::min(r,n-r);
  std::uint64_t v=1;
  for(int i=1;i<=r;++i) v=v*static_cast<std::uint64_t>(n-r+i)/static_cast<std::uint64_t>(i);
  return v;
}

std::uint64_t position_f(std::uint64_t bits,int n,int r) {
  std::uint64_t out=0;
  while(n!=r) {
    if(bits & (std::uint64_t{1}<<(n-1))) {
      out+=choose(n-1,r);
      --n; --r;
    } else --n;
  }
  return out;
}

std::uint64_t bearoff6(const Side& a) {
  int j=5;
  for(int i=0;i<6;++i) j+=a[static_cast<std::size_t>(i)];
  if(j>=63) throw std::runtime_error("bearoff rank bitset overflow");
  std::uint64_t bits=std::uint64_t{1}<<j;
  const int n=j+1;
  for(int i=0;i<5;++i) {
    j-=a[static_cast<std::size_t>(i)]+1;
    bits|=std::uint64_t{1}<<j;
  }
  return position_f(bits,n,6);
}

bool crashed(const Side& a,int total) {
  if(total<=6) return true;
  const int p0=a[0];
  if(p0>1) {
    if(total-p0<=6) return true;
    if(a[1]>1 && total+1-p0-a[1]<=6) return true;
  } else if(total-(a[1]-1)<=6) return true;
  return false;
}

int raw_class(const State& s) {
  auto [a,b]=canonical(s);
  const auto f0=features(a), f1=features(b);
  if(f0.back<0 || f1.back<0) return 0;
  if(f0.back+f1.back>22) {
    if(crashed(a,f0.total) || crashed(b,f1.total)) return 5;
    if(f0.back+f1.back==24 && a[static_cast<std::size_t>(f0.back)]>1 && b[static_cast<std::size_t>(f1.back)]>1) return 6;
    if(std::abs(f0.pip-f1.pip)>=45) {
      int m0=0,m1=0;
      for(int i=19;i<24;++i) {
        if(a[static_cast<std::size_t>(i)]>1) ++m0;
        if(b[static_cast<std::size_t>(i)]>1) ++m1;
      }
      return (m0>=2 || m1>=2) ? 7 : 4;
    }
    return 4;
  }
  if(f0.back>5 || f1.back>5) return 3;
  if((f0.total==15 || f1.total==15) && (f0.total<7 || f1.total<7)) return 3;
  const auto r0=bearoff6(a), r1=bearoff6(b);
  if(r0>54263 || r1>54263) return 3;
  if(r0>923 || r1>923) return 2;
  return 1;
}

int positive_front(const State& s) {
  for(int i=25;i>=0;--i) if(s[static_cast<std::size_t>(i)]>0) return i;
  return 0;
}
int lowest_negative(const State& s) {
  for(int i=0;i<26;++i) if(s[static_cast<std::size_t>(i)]<0) return i;
  return 25;
}
int checker_count(const State& s,int sign) {
  int n=0;
  for(auto v:s) {
    if(sign==1 && v>0) n+=v;
    if(sign==-1 && v<0) n-=v;
  }
  return n;
}

double board_efficiency(const State& s,int side,bool helper_flag) {
  if(positive_front(s)>lowest_negative(s)) return 1.0;
  if(side==1) {
    int n=checker_count(s,-1);
    if(helper_flag) n-=2;
    if(n<=0) return 0.0;
    if(n<=2) return 0.25;
    if(n<=4) return 0.5;
    if(n<=6) return 0.75;
    return kRaceMax;
  }
  const int n=checker_count(s,-side);
  return n>=2 ? kRaceMax : 0.0;
}

State mirror(const State& s) {
  State out{};
  for(int i=0;i<26;++i) out[static_cast<std::size_t>(i)]=-s[static_cast<std::size_t>(25-i)];
  return out;
}
int pip_metric(const State& s) {
  int p=0;
  for(int i=0;i<26;++i) if(s[static_cast<std::size_t>(i)]>0) p+=i*s[static_cast<std::size_t>(i)];
  return p;
}
double class3_efficiency(const State& s) {
  const int m=std::max(pip_metric(s),pip_metric(mirror(s)));
  const double e=static_cast<double>(kClass3BaseF) +
    (static_cast<double>(kClass3TargetF)-static_cast<double>(kClass3BaseF))*static_cast<double>(m-30)/90.0;
  const double clamped=std::max(static_cast<double>(kClass3BaseF),std::min(static_cast<double>(kClass3TopF),e));
  return static_cast<double>(static_cast<float>(clamped)); // XG FSTPS then FLDS
}

double cube_efficiency(const State& s,int cls,bool flag,int side=1,int state20=-1,int state24=-1,bool force_one=false) {
  if(force_one) return 1.0;
  const bool helper_flag=!flag;
  if(state20==2 && state24==2) return board_efficiency(s,side,helper_flag);
  if(cls==3) return class3_efficiency(s);
  if(cls==4 || cls==5) return static_cast<double>(kEffDefaultF);
  if(cls==7) return static_cast<double>(kEffClass7F);
  return board_efficiency(s,side,helper_flag)*static_cast<double>(kEffDefaultF);
}

float blend_f32(float live,float dead,float eff) {
  const long double v=static_cast<long double>(eff)*live + (1.0L-static_cast<long double>(eff))*dead;
  return static_cast<float>(v);
}

State make(std::initializer_list<int> xs) {
  if(xs.size()!=26) throw std::runtime_error("state width");
  State s{}; std::size_t i=0;
  for(int v:xs) s[i++]=static_cast<std::int8_t>(v);
  return s;
}

void selftest() {
  assert(choose(12,6)-1==923);
  assert(choose(21,6)-1==54263);

  State c0{}; c0[1]=15;
  State c1{}; c1[1]=6; c1[24]=-6;
  const State c2=make({0,3,3,3,3,3,0,0,0,0,0,0,0,0,0,0,0,0,0,0,-3,-3,-3,-3,-3,0});
  State c3{}; c3[7]=15; c3[18]=-15;
  const State c4=make({0,2,0,0,0,0,-5,0,-3,0,0,0,5,-5,0,0,0,3,0,5,0,0,0,0,-2,0});
  State c5{}; c5[13]=6; c5[12]=-15;
  State c6{}; c6[13]=15; c6[12]=-15;
  State c7{}; c7[20]=7; c7[24]=8; c7[22]=-15;
  const std::array<State,8> cases={c0,c1,c2,c3,c4,c5,c6,c7};
  const std::array<double,8> eff0={0.0,0.35249999165535,0.622058808806047,0.683333337306976,0.704999983310699,0.704999983310699,0.704999983310699,0.850000023841858};
  const std::array<double,8> eff1={0.0,0.528749987483025,0.622058808806047,0.683333337306976,0.704999983310699,0.704999983310699,0.704999983310699,0.850000023841858};
  double maxerr=0.0;
  for(int i=0;i<8;++i) {
    const int cls=raw_class(cases[static_cast<std::size_t>(i)]);
    assert(cls==i);
    for(int flag=0;flag<2;++flag) {
      const double got=cube_efficiency(cases[static_cast<std::size_t>(i)],cls,flag!=0);
      const double expected=(flag?eff1:eff0)[static_cast<std::size_t>(i)];
      maxerr=std::max(maxerr,std::abs(got-expected));
      if(std::abs(got-expected)>5e-13) throw std::runtime_error("dispatcher mismatch");
    }
  }
  std::cout << "R42_CPP_XG_REFERENCE=PASS cases=16 max_err=" << maxerr << "\n";
}
} // namespace xgref

int main(){ xgref::selftest(); }
