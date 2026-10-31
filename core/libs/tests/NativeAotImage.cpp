#include "prx/libc/include/ApplicationHeap.hpp"
#include "prx/libc/include/NativeAotImage.hpp"
#include <array>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>

static void Require(bool value, const char* name) {
    if (!value) {
        std::fprintf(stderr, "Native AOT image check failed: %s\n", name);
        std::abort();
    }
}

template<class Action>
static void Reject(Action action) {
    try { action(); }
    catch (const std::exception&) { return; }
    Require(false, "invalid image accepted");
}

struct Fixture {
    std::array<std::uint64_t, 8> process{};
    std::array<std::uint64_t, 7> libc{};
    std::array<std::uint64_t, 15> replacement{};
    NativeAotDataRange ranges[3]{};
    Elf64_Phdr headers[2]{{PT_LOAD, PF_R | PF_X, 0x4000, 0, 0, 0x100, 0x100, 0x4000}, {PT_LOAD, PF_R | PF_W, 0x8000, 0x8000, 0x8000, 0x10, 0x20000, 0x4000}};
    NativeAotImage image{};

    Fixture() {
        process[0] = sizeof(process);
        process[1] = 0x4942524f;
        process[7] = reinterpret_cast<std::uint64_t>(libc.data());
        libc[0] = sizeof(libc);
        libc[6] = reinterpret_cast<std::uint64_t>(replacement.data());
        replacement[0] = sizeof(replacement);
        replacement[1] = 2;
        ranges[0] = {process.data(), sizeof(process)};
        ranges[1] = {libc.data(), sizeof(libc)};
        ranges[2] = {replacement.data(), sizeof(replacement)};
        image = {2, ranges, 3, nullptr, 0, process.data(), sizeof(process), headers, 2};
    }
};

static void AllocatorInitializer() {}

int main() {
    Reject([] { ApplicationProcessParameters_nid_no_patch(); });
    Reject([] { NativeAotRegisterImage_nid_no_patch(nullptr); });
    {
        Fixture value;
        value.image.version = 1;
        Reject([&] { NativeAotRegisterImage_nid_no_patch(&value.image); });
    }
    {
        Fixture value;
        value.image.programHeaders = nullptr;
        Reject([&] { NativeAotRegisterImage_nid_no_patch(&value.image); });
    }
    {
        Fixture value;
        value.image.programHeaderCount = 0x10000;
        Reject([&] { NativeAotRegisterImage_nid_no_patch(&value.image); });
    }
    const Elf64_Phdr* headers = nullptr;
    Require(NativeAotImageProgramHeaders_nid_no_patch(&headers) == 0, "no program headers before registration");
    {
        Fixture value;
        value.image.processParameterBytes = 65;
        Reject([&] { NativeAotRegisterImage_nid_no_patch(&value.image); });
    }
    {
        Fixture value;
        value.process[7] = 1;
        Reject([&] { NativeAotRegisterImage_nid_no_patch(&value.image); });
    }
    {
        Fixture value;
        value.libc[6] = reinterpret_cast<std::uint64_t>(value.replacement.data() + 1);
        Reject([&] { NativeAotRegisterImage_nid_no_patch(&value.image); });
    }
    {
        Fixture value;
        value.replacement[2] = reinterpret_cast<std::uint64_t>(&AllocatorInitializer);
        Reject([&] { NativeAotRegisterImage_nid_no_patch(&value.image); });
    }
    {
        Fixture value;
        value.ranges[1].bytes = ~std::size_t(0);
        Reject([&] { NativeAotRegisterImage_nid_no_patch(&value.image); });
    }
    {
        Fixture value;
        value.process[1] = 0;
        Reject([&] { NativeAotRegisterImage_nid_no_patch(&value.image); });
    }
    {
        Fixture value;
        value.replacement[1] = 3;
        Reject([&] { NativeAotRegisterImage_nid_no_patch(&value.image); });
    }
    Fixture valid;
    const void* callbacks[]{reinterpret_cast<const void*>(&AllocatorInitializer)};
    valid.image.functions = callbacks;
    valid.image.functionCount = 1;
    valid.replacement[2] = reinterpret_cast<std::uint64_t>(&AllocatorInitializer);
    NativeAotRegisterImage_nid_no_patch(&valid.image);
    valid.headers[0].p_memsz = 1;
    valid.image.programHeaderCount = 1;
    NativeAotRegisterImage_nid_no_patch(&valid.image);
    Require(ApplicationProcessParameters_nid_no_patch() == valid.process.data(), "registered process parameters");
    Require(NativeAotImageProgramHeaders_nid_no_patch(&headers) == 2 && headers != valid.headers, "program headers copied once");
    Require(headers[0].p_memsz == 0x100 && headers[1].p_flags == (PF_R | PF_W) && headers[1].p_memsz == 0x20000, "program header fields");
    Fixture another;
    Reject([&] { NativeAotRegisterImage_nid_no_patch(&another.image); });
}
