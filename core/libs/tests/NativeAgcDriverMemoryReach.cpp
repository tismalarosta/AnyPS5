#include "prx/libSceAgcDriver/Execution/include/Driver.hpp"
#include <cstdint>
#include <source_location>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <utility>
#include <vector>

static void Require(bool condition, std::source_location source = std::source_location::current()) {
    if (!condition) throw std::runtime_error("native AGC driver memory reach failure at " + std::to_string(source.line()));
}

constexpr std::uint64_t InlineConstantReach = 0x4100000000ull;

static std::vector<std::pair<void*, std::size_t>> FillBelowReach() {
    std::vector<std::pair<void*, std::size_t>> reserved;
    for (std::size_t bytes = std::size_t{1} << 30u; bytes >= (std::size_t{2} << 20u); bytes /= 2u) {
        for (;;) {
            void* placed = mmap(reinterpret_cast<void*>(0x100000000ull), bytes, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
            Require(placed != MAP_FAILED);
            if (reinterpret_cast<std::uint64_t>(placed) + bytes > InlineConstantReach) {
                munmap(placed, bytes);
                break;
            }
            reserved.emplace_back(placed, bytes);
        }
    }
    return reserved;
}

int main() {
    static_cast<void>(AgcDriverDispatchesAdoptedAhead_nid_postfix());
    const auto reserved = FillBelowReach();
    std::string reason;
    try {
        static_cast<void>(AgcDriverStaticTable_nid_postfix());
    } catch (const std::runtime_error& error) {
        reason = error.what();
    }
    Require(reason == "the relocated AGC driver memory is above 0x40ffffffff, where a shader's inline constant cannot reach it");
    for (const auto& [address, bytes] : reserved) munmap(address, bytes);
    const auto table = reinterpret_cast<std::uint64_t>(AgcDriverStaticTable_nid_postfix());
    Require(table != 0xfe0040000ull && table + 0x60u <= InlineConstantReach);
    return 0;
}
