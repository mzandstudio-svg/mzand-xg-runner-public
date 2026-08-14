#!/usr/bin/env python3
from pathlib import Path
import textwrap

ROOT = Path('MZAND_PADDED_INPUT_ENGINE_V1')

def put(path: str, text: str):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text).lstrip(), encoding='utf-8')

put('CMakeLists.txt', r'''
cmake_minimum_required(VERSION 3.20)
project(mzand_padded_input_engine_v1 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(mzand_padded_input INTERFACE)
target_include_directories(mzand_padded_input INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/include)

foreach(N IN ITEMS 252 254 256 258)
  add_executable(mzand_eval_${N} src/main.cpp)
  target_link_libraries(mzand_eval_${N} PRIVATE mzand_padded_input)
  target_compile_definitions(mzand_eval_${N} PRIVATE MZAND_DECLARED_INPUTS=${N})
endforeach()

add_executable(mzand_padded_parity_tests tests/test_parity.cpp)
target_link_libraries(mzand_padded_parity_tests PRIVATE mzand_padded_input)

enable_testing()
add_test(NAME mzand_padded_parity_tests COMMAND mzand_padded_parity_tests)
''')

put('include/mzand/padded_input.hpp', r'''
#pragma once
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <type_traits>

namespace mzand::padded {

inline constexpr std::size_t kActiveInputs = 250;
inline constexpr std::array<std::size_t,4> kSupportedDeclaredInputs{252,254,256,258};

constexpr bool supported(std::size_t n) {
  for (auto v : kSupportedDeclaredInputs) if (v == n) return true;
  return false;
}

struct ReservedSlotError : std::runtime_error {
  using std::runtime_error::runtime_error;
};

template<std::size_t DeclaredInputs>
struct InputVector {
  static_assert(DeclaredInputs >= kActiveInputs);
  static_assert(DeclaredInputs == 252 || DeclaredInputs == 254 ||
                DeclaredInputs == 256 || DeclaredInputs == 258,
                "Supported declared input sizes are 252/254/256/258");

  static constexpr std::size_t declared_inputs = DeclaredInputs;
  static constexpr std::size_t active_inputs = kActiveInputs;
  static constexpr std::size_t reserved_inputs = DeclaredInputs - kActiveInputs;

  std::array<float, DeclaredInputs> values{};

  static InputVector from_active(const std::array<float,kActiveInputs>& base) {
    InputVector out{};
    for (std::size_t i=0;i<kActiveInputs;++i) out.values[i]=base[i];
    for (std::size_t i=kActiveInputs;i<DeclaredInputs;++i) out.values[i]=0.0f;
    return out;
  }

  std::array<float,kActiveInputs> active_copy() const {
    std::array<float,kActiveInputs> out{};
    for (std::size_t i=0;i<kActiveInputs;++i) out[i]=values[i];
    return out;
  }

  void enforce_reserved_zero() const {
    for (std::size_t i=kActiveInputs;i<DeclaredInputs;++i) {
      if (values[i] != 0.0f) {
        throw ReservedSlotError("reserved MZand input slot " + std::to_string(i) + " must remain zero");
      }
    }
  }
};

// The contract is intentionally strict: the padded API is larger, but the legacy
// evaluator still receives the exact same 250 floats in the exact same order.
// No extra multiply/add operations are inserted into the legacy accumulation path.
template<std::size_t DeclaredInputs, class LegacyEvaluator250>
auto evaluate_strict(const InputVector<DeclaredInputs>& padded, LegacyEvaluator250&& legacy) {
  padded.enforce_reserved_zero();
  const auto active = padded.active_copy();
  return legacy(active);
}

// Deterministic reference kernel used only for parity testing and examples.
// Replace this callable with the existing MZand 250-input evaluator in integration.
struct ReferenceKernel250 {
  using Output = std::array<float,5>;

  Output operator()(const std::array<float,kActiveInputs>& x) const {
    Output out{};
    for (std::size_t o=0;o<out.size();++o) {
      float acc = static_cast<float>(o) * 0.03125f - 0.125f;
      for (std::size_t i=0;i<kActiveInputs;++i) {
        const std::uint32_t m = static_cast<std::uint32_t>((i+1)*(o+3)*2654435761u);
        const float w = static_cast<float>(static_cast<int>(m % 2001u) - 1000) / 8192.0f;
        acc += x[i] * w;
      }
      out[o] = 1.0f / (1.0f + std::exp(-acc));
    }
    return out;
  }
};

inline std::array<float,kActiveInputs> deterministic_input(std::uint32_t seed) {
  std::array<float,kActiveInputs> x{};
  std::uint32_t s=seed ? seed : 1u;
  for (std::size_t i=0;i<x.size();++i) {
    s = 1664525u*s + 1013904223u;
    const int q = static_cast<int>((s >> 8) % 4097u) - 2048;
    x[i] = static_cast<float>(q) / 1024.0f;
  }
  return x;
}

template<class A, class B>
bool bitwise_equal_array(const A& a, const B& b) {
  static_assert(std::tuple_size_v<A> == std::tuple_size_v<B>);
  for (std::size_t i=0;i<a.size();++i) {
    if (std::bit_cast<std::uint32_t>(a[i]) != std::bit_cast<std::uint32_t>(b[i])) return false;
  }
  return true;
}

} // namespace mzand::padded
''')

put('src/main.cpp', r'''
#include <mzand/padded_input.hpp>
#include <cstdlib>
#include <iomanip>
#include <iostream>

#ifndef MZAND_DECLARED_INPUTS
#define MZAND_DECLARED_INPUTS 252
#endif

int main(int argc, char** argv) {
  using namespace mzand::padded;
  constexpr std::size_t N = MZAND_DECLARED_INPUTS;
  const std::uint32_t seed = argc > 1 ? static_cast<std::uint32_t>(std::strtoul(argv[1],nullptr,10)) : 1u;
  const auto base = deterministic_input(seed);
  const ReferenceKernel250 legacy{};
  const auto baseline = legacy(base);
  const auto padded = InputVector<N>::from_active(base);
  const auto result = evaluate_strict(padded, legacy);

  std::cout << "MZand Padded Input Engine V1\n";
  std::cout << "declared_inputs=" << N << "\n";
  std::cout << "active_inputs=" << kActiveInputs << "\n";
  std::cout << "reserved_inputs=" << (N-kActiveInputs) << "\n";
  std::cout << "reserved_policy=STRICT_ZERO\n";
  std::cout << "bitwise_output_parity=" << (bitwise_equal_array(baseline,result) ? "true" : "false") << "\n";
  std::cout << std::setprecision(9);
  for (std::size_t i=0;i<result.size();++i) std::cout << "output[" << i << "]=" << result[i] << "\n";
  return bitwise_equal_array(baseline,result) ? 0 : 2;
}
''')

put('tests/test_parity.cpp', r'''
#include <mzand/padded_input.hpp>
#include <array>
#include <bit>
#include <cstdint>
#include <iostream>

using namespace mzand::padded;

template<std::size_t N>
bool check_variant() {
  ReferenceKernel250 legacy{};
  for (std::uint32_t seed=1; seed<=1000; ++seed) {
    const auto base = deterministic_input(seed);
    const auto ref = legacy(base);
    auto padded = InputVector<N>::from_active(base);
    const auto got = evaluate_strict(padded, legacy);
    if (!bitwise_equal_array(ref,got)) return false;
    for (std::size_t i=kActiveInputs;i<N;++i) if (padded.values[i] != 0.0f) return false;
  }
  auto bad = InputVector<N>::from_active(deterministic_input(7));
  bad.values[N-1] = 1.0f;
  try {
    (void)evaluate_strict(bad, legacy);
    return false;
  } catch (const ReservedSlotError&) {}
  return true;
}

int main() {
  const bool a=check_variant<252>();
  const bool b=check_variant<254>();
  const bool c=check_variant<256>();
  const bool d=check_variant<258>();
  std::cout << "252=" << a << " 254=" << b << " 256=" << c << " 258=" << d << "\n";
  std::cout << "vectors_per_variant=1000\n";
  std::cout << "parity_requirement=BITWISE\n";
  return (a&&b&&c&&d) ? 0 : 1;
}
''')

put('README.md', r'''
# MZand Padded Input Engine V1

Research build for extending a legacy **250-input** evaluator to declared input sizes
**252, 254, 256 and 258** while preserving the old numerical result.

## Contract

The first **250 inputs are active** and remain in their original order.
All additional slots are reserved and initialized to exact `0.0f`:

- 252: reserved indices `250..251`
- 254: reserved indices `250..253`
- 256: reserved indices `250..255`
- 258: reserved indices `250..257`

The default policy is `STRICT_ZERO`. A non-zero reserved slot throws
`ReservedSlotError`. This is deliberate: reserved inputs cannot silently change engine
behavior.

## Why output stays unchanged

The padded wrapper does **not** add extra terms to the legacy network computation.
It validates the tail and passes an exact copy of indices `0..249` to the existing
250-input evaluator. Therefore the old accumulation order and output path are unchanged.
The regression suite requires **bitwise equality**, not merely a tolerance.

## Integration with the real MZand evaluator

In `evaluate_strict(...)`, replace the example `ReferenceKernel250` callable with the
existing MZand function that currently accepts `std::array<float,250>` (or adapt its
existing 250-float buffer to that callable). No model retraining is required for the
reserved-zero stage.

Do not renumber or rewrite the first 250 features. The declared larger vector is an API
and research-extension layer only until a reserved slot is explicitly assigned a new
feature and trained/validated.

## Builds

Four executables are generated:

- `mzand_eval_252`
- `mzand_eval_254`
- `mzand_eval_256`
- `mzand_eval_258`

Each reports its declared/active/reserved counts and verifies bitwise output parity.

## Build on macOS

Run:

```bash
chmod +x BUILD_MAC.command
./BUILD_MAC.command
```

The script builds all four variants and runs CTest.

## Research rule for future slots

Reserved slots should be activated in pairs only through a versioned feature map.
When any slot becomes active, remove it from the strict-zero range, add explicit
normalization, train or fit the corresponding weights, and create a new held-out
regression baseline. Until then, it must remain zero.

This package changes dimensional scaffolding only. It is not evidence of improved playing
strength or XG parity.
''')

put('docs/INPUT_LAYOUT.md', r'''
# Input Layout

The invariant region is always:

```text
0..249   ACTIVE_LEGACY_250   unchanged
```

Reserved tails:

```text
252 build: 250..251  RESERVED_R1_0, RESERVED_R1_1
254 build: 250..253  RESERVED_R1_0..RESERVED_R2_1
256 build: 250..255  RESERVED_R1_0..RESERVED_R3_1
258 build: 250..257  RESERVED_R1_0..RESERVED_R4_1
```

All reserved fields are `float`, default `+0.0f`, and guarded by strict validation.

The design intentionally leaves semantic names unassigned. This prevents accidental use
of speculative features. When a pair is given meaning later, document its exact board
orientation, normalization, valid range, and model-training provenance before enabling it.
''')

put('docs/INTEGRATION.md', r'''
# Integration Notes

1. Keep the existing 250-feature builder byte-for-byte unchanged if possible.
2. Build the normal `std::array<float,250>` first.
3. Create the selected padded type with `InputVector<N>::from_active(base)`.
4. Keep every reserved field zero.
5. Call `evaluate_strict(padded, legacy_evaluator_250)`.
6. Run the parity regression before changing any production routing.

Example:

```cpp
std::array<float,250> base = build_existing_mzand_features(board);
auto padded = mzand::padded::InputVector<258>::from_active(base);
auto y = mzand::padded::evaluate_strict(padded, [&](const auto& x250) {
    return existing_mzand_network_forward(x250);
});
```

This approach gives the surrounding engine a 258-slot research vector while preserving
exactly the old evaluator input and output until reserved slots are intentionally enabled.
''')

put('BUILD_MAC.command', r'''
#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
rm -rf build
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j "$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"
ctest --test-dir build --output-on-failure
for n in 252 254 256 258; do
  echo "--- mzand_eval_${n} ---"
  "$ROOT/build/mzand_eval_${n}" 12345
 done
''')

put('VERSION.txt', 'MZAND_PADDED_INPUT_ENGINE_V1\nactive=250\ndeclared=252,254,256,258\nreserved_policy=STRICT_ZERO\nparity=BITWISE_REQUIRED\n')

print(ROOT.resolve())
