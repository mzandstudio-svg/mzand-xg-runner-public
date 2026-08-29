#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <stdexcept>

namespace xgbranchb {

static float f32(long double v) { return static_cast<float>(v); }

struct XKnots {
  std::array<float,4> x{};
  float branch_b_limit{};
  float main_t2{};
};

// Recovered from 0x9DBA90 money path plus caller 0x9DCD84..0x9DCDB3.
// mode2/mode3 are qword slots whose values originated from float32 stores in
// 0x9DA770. Every threshold below is explicitly materialized to dword by XG.
XKnots build_money_branch_b_x(double mode2, double mode3) {
  const long double a = static_cast<long double>(mode2);
  const long double b = static_cast<long double>(mode3);
  const long double s = a + b;

  const float t1 = f32((b - 0.5L) / (s + 0.5L));
  const float q_other = f32((a - 0.5L) / (s + 0.5L));
  const float t2 = f32(1.0L - static_cast<long double>(q_other));

  // 0x9DBEB2..0x9DBECF -> arg4+0x0c. Branch-B caller passes arg4
  // as &caller[ebp-0x40], so this is exactly caller local [ebp-0x34].
  const float limit = f32((b + 1.0L) / s);

  XKnots out;
  out.main_t2 = t2;
  out.branch_b_limit = limit;
  out.x = {0.0f, t1, (limit < t2 ? limit : t2), 1.0f};
  return out;
}

static void nearf(float a, float b, float eps=2e-6f) {
  if (std::fabs(a-b) > eps) throw std::runtime_error("R58 float mismatch");
}

void selftest() {
  // Symmetric positive money case: the additional Branch-B bound is 1.0,
  // so the main R53 t2=0.8 remains selected.
  {
    const auto k = build_money_branch_b_x(1.0, 1.0);
    nearf(k.x[0], 0.0f);
    nearf(k.x[1], 0.2f);
    nearf(k.main_t2, 0.8f);
    nearf(k.branch_b_limit, 1.0f);
    nearf(k.x[2], 0.8f);
    nearf(k.x[3], 1.0f);
  }

  // Asymmetric positive example. This verifies the recovered extra output is
  // independently materialized even when it does not tighten X2.
  {
    const auto k = build_money_branch_b_x(2.0, 3.0);
    const float q = static_cast<float>(1.5L / 5.5L);
    const float t2 = static_cast<float>(1.0L - static_cast<long double>(q));
    nearf(k.main_t2, t2);
    nearf(k.branch_b_limit, static_cast<float>(4.0L/5.0L));
    nearf(k.x[2], std::min(k.main_t2, k.branch_b_limit));
  }

  // Generic arithmetic-domain case chosen specifically to exercise the
  // caller's strict '<' replacement branch. This is a reference arithmetic
  // test, not a claim that XG's evaluator emits these mode values.
  {
    const auto k = build_money_branch_b_x(-2.0, 0.5);
    if (!(k.branch_b_limit < k.main_t2))
      throw std::runtime_error("R58 clip branch not exercised");
    nearf(k.x[2], k.branch_b_limit);
  }

  std::cout << "R58_XG_MONEY_BRANCH_B_REFERENCE=PASS\n";
  std::cout << "R58_PRODUCTION_BEHAVIOR_CHANGED=NO\n";
}

} // namespace xgbranchb

int main() {
  xgbranchb::selftest();
  return 0;
}
