#include <cmath>
#include <cstdint>
#include <iostream>
#include <stdexcept>

namespace xgdead {

static float f32(long double x) {
  return static_cast<float>(x);
}

// Recovered 0x6FFD90 money-context branch for the two fixed basis vectors
// used by 0x6FFEF4.  The caller 0x9DC770 copies state+0x20 into temp+0;
// this path is entered only when state+0x20 == -1, so 0x6FFEF4 forces its
// local context pair to {-1,-1} before calling 0x6FFD90.
//
// basis A = {0,0,0,0,0} -> +cube_value
// basis B = {1,0,0,0,0} -> -cube_value
//
// This function keeps the recovered instruction-level staging explicit.
static float basis_money(bool basis_b, std::int32_t cube_value) {
  const float b0 = basis_b ? 1.0f : 0.0f;

  // 0x6FFDAE special numeric branch (cube_value==1 and odd caller flag)
  // produces the same result for these two basis vectors, so no semantic
  // interpretation of that flag is required for the recovered endpoints.
  const long double core =
      (2.0L * static_cast<long double>(b0) - 1.0L) *
      static_cast<long double>(cube_value);
  const float materialized = f32(core); // FSTP dword [ebp-0xc]
  return -materialized;                 // FLD then FCHS return
}

// Exact recovered sequence in 0x6FFEF4 for temp+0x1c == -1.0f:
//   t = (current_equity + 1) * 0.5
//   dead = B + t * (A - B)
//   FSTP dword temp+0x1c
// A/B themselves are materialized to dword after the two 0x6FFD90 calls.
float money_dead_endpoint_f32(float current_equity,
                              std::int32_t cube_value) {
  const float a = basis_money(false, cube_value);
  const float b = basis_money(true, cube_value);

  const long double t =
      (static_cast<long double>(current_equity) + 1.0L) * 0.5L;
  const long double out =
      static_cast<long double>(b) +
      t * (static_cast<long double>(a) - static_cast<long double>(b));
  return f32(out);
}

static void nearf(float a, float b, float eps=2e-6f) {
  if (std::fabs(a-b) > eps)
    throw std::runtime_error("R56 float mismatch");
}

void selftest() {
  // The fixed basis vectors collapse exactly to +/- cube value.
  nearf(basis_money(false, 1), 1.0f);
  nearf(basis_money(true, 1), -1.0f);
  nearf(basis_money(false, 2), 2.0f);
  nearf(basis_money(true, 2), -2.0f);
  nearf(basis_money(false, 8), 8.0f);
  nearf(basis_money(true, 8), -8.0f);

  // Representative values. The affine transform is algebraically C*equity,
  // but the implementation above preserves XG's recovered operation order.
  nearf(money_dead_endpoint_f32(-1.0f, 1), -1.0f);
  nearf(money_dead_endpoint_f32( 0.0f, 1),  0.0f);
  nearf(money_dead_endpoint_f32( 1.0f, 1),  1.0f);
  nearf(money_dead_endpoint_f32( 0.25f, 2), 0.5f);
  nearf(money_dead_endpoint_f32(-0.375f, 4), -1.5f);

  // Cross-check the affine collapse against float32(C * eq) for a dense set
  // of finite float inputs representative of cubeless equity outputs.
  for (int c : {1,2,4,8,16,32,64}) {
    for (int i=-1000;i<=1000;++i) {
      const float eq = static_cast<float>(i) / 1000.0f;
      const float got = money_dead_endpoint_f32(eq, c);
      const float simplified = f32(
          static_cast<long double>(eq) * static_cast<long double>(c));
      if (got != simplified)
        throw std::runtime_error("R56 affine collapse mismatch");
    }
  }

  std::cout << "R56_XG_MONEY_DEAD_ENDPOINT_REFERENCE=PASS\n";
}

} // namespace xgdead

int main() {
  xgdead::selftest();
  return 0;
}
