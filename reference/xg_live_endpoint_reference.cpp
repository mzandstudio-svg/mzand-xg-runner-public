#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace xglive {

struct Knots {
  std::array<float,4> x{};
  std::array<float,4> y{};
};

// XG uses x87 intermediates but materializes each recovered knot/output with
// FSTP dword.  long double is used here only as an explicit wider staging
// type; every proven dword boundary is represented by f32().
static float f32(long double v) {
  return static_cast<float>(v);
}

// Recovered from 0x9DBA90 money early-return branch called by 0x9DC770.
// mode2/mode3 are qword slots whose values originate from float32 evaluator
// results in 0x9DA770.
Knots build_money_live_knots(double mode2,
                             double mode3,
                             std::int32_t cube_value,
                             std::int32_t state30_flags) {
  const long double a = static_cast<long double>(mode2);
  const long double b = static_cast<long double>(mode3);
  const long double s = a + b;

  const float t1 = f32((b - 0.5L) / (s + 0.5L));

  // XG first stores this complementary-side threshold to float32, reloads it,
  // then performs 1.0 - q and stores the result to float32.
  const float q_other = f32((a - 0.5L) / (s + 0.5L));
  const float t2 = f32(1.0L - static_cast<long double>(q_other));

  Knots k;
  k.x = {0.0f, t1, t2, 1.0f};

  if ((state30_flags & 1) == 1 && cube_value == 1) {
    k.y = {-1.0f, -1.0f, 1.0f, 1.0f};
  } else {
    const long double c = static_cast<long double>(cube_value);
    k.y[0] = f32(-b * c);
    k.y[1] = f32(-c);
    k.y[2] = f32(c);
    k.y[3] = f32(a * c);
  }
  return k;
}

// Recovered 0x9DC630 segment helper. Inputs are already float32 because XG
// reads the caller's dword knot arrays and clamped dword x.
float interp_f32(float x, float xi, float xj, float yi, float yj) {
  const long double ratio =
      (static_cast<long double>(x) - static_cast<long double>(xi)) /
      (static_cast<long double>(xj) - static_cast<long double>(xi));
  const long double v = static_cast<long double>(yi) +
      ratio * (static_cast<long double>(yj) - static_cast<long double>(yi));
  return f32(v);
}

// Recovered from 0x9DC690 and its three call sites in 0x9DC770.
// Numeric owner semantics are intentionally not renamed to player/opponent
// until the dynamic ownership trace is proven.
float live_endpoint_f32(const Knots& k, float input_x, std::int32_t owner_numeric) {
  float x = input_x;
  if (x < 0.0f) x = 0.0f;
  if (x > 1.0f) x = 1.0f;

  switch (owner_numeric) {
    case 0: {
      // 0x9DC841: indices (1,2,3,4), i.e. all three segments.
      if (x <= k.x[1]) {
        // 0x9DC690 explicitly skips the first segment when its width is zero.
        if (k.x[1] != k.x[0])
          return interp_f32(x, k.x[0], k.x[1], k.y[0], k.y[1]);
      }
      if (x <= k.x[2])
        return interp_f32(x, k.x[1], k.x[2], k.y[1], k.y[2]);
      if (x <= k.x[3])
        return interp_f32(x, k.x[2], k.x[3], k.y[2], k.y[3]);
      return 0.0f;
    }
    case 1: {
      // 0x9DC81D: indices (1,2,4,-1). Clamp makes sentinel segment unreachable.
      if (x <= k.x[1]) {
        if (k.x[1] != k.x[0])
          return interp_f32(x, k.x[0], k.x[1], k.y[0], k.y[1]);
      }
      if (x <= k.x[3])
        return interp_f32(x, k.x[1], k.x[3], k.y[1], k.y[3]);
      return 0.0f;
    }
    case -1: {
      // 0x9DC865: indices (1,3,4,-1).
      if (x <= k.x[2]) {
        if (k.x[2] != k.x[0])
          return interp_f32(x, k.x[0], k.x[2], k.y[0], k.y[2]);
      }
      if (x <= k.x[3])
        return interp_f32(x, k.x[2], k.x[3], k.y[2], k.y[3]);
      return 0.0f;
    }
    default:
      // 0x9DC889 zeros [ebp-0x08] for other owner values.
      return 0.0f;
  }
}

static void nearf(float a, float b, float eps=2e-6f) {
  if (std::fabs(a-b) > eps) {
    throw std::runtime_error("float mismatch");
  }
}

void selftest() {
  // Symmetric no-gammon multiplier case gives the classic 20/80 thresholds.
  const auto s = build_money_live_knots(1.0, 1.0, 1, 0);
  nearf(s.x[0], 0.0f);
  nearf(s.x[1], 0.2f);
  nearf(s.x[2], 0.8f);
  nearf(s.x[3], 1.0f);
  nearf(s.y[0], -1.0f);
  nearf(s.y[1], -1.0f);
  nearf(s.y[2], 1.0f);
  nearf(s.y[3], 1.0f);

  nearf(live_endpoint_f32(s, 0.0f, 0), -1.0f);
  nearf(live_endpoint_f32(s, 0.2f, 0), -1.0f);
  nearf(live_endpoint_f32(s, 0.5f, 0), 0.0f);
  nearf(live_endpoint_f32(s, 0.8f, 0), 1.0f);
  nearf(live_endpoint_f32(s, 1.0f, 0), 1.0f);

  // Numeric owner +1 skips the X2/Y2 knot; numeric owner -1 skips X1/Y1.
  nearf(live_endpoint_f32(s, 0.5f, 1), -0.25f);
  nearf(live_endpoint_f32(s, 0.5f, -1), 0.25f);

  // Input is clamped by 0x9DC690 before segment selection.
  nearf(live_endpoint_f32(s, -5.0f, 0), -1.0f);
  nearf(live_endpoint_f32(s, 5.0f, 0), 1.0f);

  // Proven special numeric flag/cube branch suppresses mode2/mode3-scaled tails.
  const auto special = build_money_live_knots(2.0, 3.0, 1, 1);
  nearf(special.y[0], -1.0f);
  nearf(special.y[1], -1.0f);
  nearf(special.y[2], 1.0f);
  nearf(special.y[3], 1.0f);

  // General payoff branch retains mode3 on the negative tail and mode2 on
  // the positive tail, scaled by the integer cube value.
  const auto g = build_money_live_knots(2.0, 3.0, 2, 0);
  nearf(g.x[1], static_cast<float>(2.5/5.5));
  nearf(g.x[2], static_cast<float>(1.0 - static_cast<float>(1.5/5.5)));
  nearf(g.y[0], -6.0f);
  nearf(g.y[1], -2.0f);
  nearf(g.y[2], 2.0f);
  nearf(g.y[3], 4.0f);

  std::cout << "R53_XG_LIVE_ENDPOINT_REFERENCE=PASS\n";
}

} // namespace xglive

int main() {
  xglive::selftest();
  return 0;
}
