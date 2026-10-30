#include "prx/libSceAgc/Misc/include/StaticBuffer.hpp"
#include "prx/libSceAgcDriver/Execution/include/Driver.hpp"
#include <array>
#include <cstdint>
#include <cstring>
#include <source_location>
#include <stdexcept>
#include <string>

static void Require(bool condition, std::source_location source = std::source_location::current()) {
    if (!condition) throw std::runtime_error("native AGC static table failure at " + std::to_string(source.line()));
}

int main() {
    std::array<std::uint64_t, 2> buffer{};
    Require(sceAgcGetStaticBuffer(6, buffer.data()) == static_cast<int>(0x8a6c000bu));
    Require(sceAgcGetStaticBuffer(0, buffer.data()) == 0);
    const auto table = reinterpret_cast<std::uintptr_t>(AgcDriverStaticTable_nid_postfix());
    Require(table != 0xfe0040000ull && table >> 32u <= 64u);
    std::array<std::uint64_t, 2> slot{};
    std::memcpy(slot.data(), reinterpret_cast<const void*>(table), sizeof(slot));
    Require(buffer == slot && slot[0] >> 48u == 16u && slot[1] == 0x0000520400000008ull);
    std::array<std::uint64_t, 16> records{};
    std::memcpy(records.data(), reinterpret_cast<const void*>(slot[0] & 0xffffffffffffull), sizeof(records));
    for (std::size_t record = 0; record < 8u; ++record) Require(records[record * 2u] == records[0] && records[record * 2u + 1u] == 0u);
    std::uint32_t routine = 0;
    std::memcpy(&routine, reinterpret_cast<const void*>(records[0]), sizeof(routine));
    Require(routine == 0xbe80200eu);
    const std::array<std::uint64_t, 2> written{0x1122334455667788ull, 0x99aabbccddeeff00ull};
    Require(sceAgcSetStaticBuffer(5, written.data()) == 0);
    std::memcpy(slot.data(), reinterpret_cast<const void*>(table + 5u * 16u), sizeof(slot));
    Require(slot == written);
    return 0;
}
