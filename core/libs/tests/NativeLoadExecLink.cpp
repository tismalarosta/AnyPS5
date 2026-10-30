#include "prx/libSceSystemService/LoadExec.hpp"
#include "prx/libSceSystemService/SystemService.hpp"
#include "prx/libc/include/general/VabiMacros.hpp"
#include <cstdint>
#include <filesystem>
#include <mach-o/dyld.h>
#include <cstring>
#include <source_location>
#include <stdexcept>
#include <string>

extern "C" {
int APS5_VABI sceSystemServiceLoadExec(const char* path, const char* const* arguments);
int APS5_VABI sigprocmask_nid_postfix(int how, const void* set, void* previousSet);
void APS5_VABI JumpBufferSaveMask_nid_no_patch(unsigned char* buffer);
}

static void Require(bool condition, std::source_location source = std::source_location::current()) {
    if (!condition) throw std::runtime_error("native LoadExec link failure at " + std::to_string(source.line()));
}

int main() {
    Require(sceSystemServiceLoadExec(nullptr, nullptr) == SYSTEM_SERVICE_ERROR_PARAMETER);
    Require(sceSystemServiceLoadExec("", nullptr) == SYSTEM_SERVICE_ERROR_PARAMETER);
    char self[4096]{};
    std::uint32_t size = sizeof(self);
    Require(_NSGetExecutablePath(self, &size) == 0);
    const char* const arguments[] = {"a", nullptr};
    bool rejected = false;
    try {
        LoadConvertedExecutable_nid_no_patch(std::filesystem::path(self), arguments);
    } catch (const std::runtime_error& error) {
        rejected = std::string(error.what()) == "LoadExec: target is not an executable x86-64 Mach-O";
    }
    Require(rejected);
    unsigned char current[16]{};
    Require(sigprocmask_nid_postfix(1, nullptr, current) == 0);
    unsigned char buffer[96]{};
    JumpBufferSaveMask_nid_no_patch(buffer);
    std::int32_t saved = 0;
    std::memcpy(&saved, buffer + 88, sizeof(saved));
    Require(saved == 1);
    Require(std::memcmp(buffer + 72, current, sizeof(current)) == 0);
    return 0;
}
