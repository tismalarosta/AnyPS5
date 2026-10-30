#include "prx/libSceAgc/Misc/include/StaticBuffer.hpp"
#include <array>
#include <cstdint>
#include <source_location>
#include <stdexcept>
#include <string>

static void Require(bool condition, std::source_location source = std::source_location::current()) {
    if (!condition) throw std::runtime_error("native AGC static table failure at " + std::to_string(source.line()));
}

int main() {
    std::array<std::uint64_t, 2> buffer{};
    Require(sceAgcGetStaticBuffer(6, buffer.data()) == static_cast<int>(0x8a6c000bu));
    std::string reason;
    try {
        sceAgcGetStaticBuffer(0, buffer.data());
    } catch (const std::runtime_error& error) {
        reason = error.what();
    }
    Require(reason == "the AGC static table at 0xfe0040000 is in the Apple ARM64 shared region guard and cannot be mapped");
    return 0;
}
