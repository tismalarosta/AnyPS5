#include "prx/libkernel/include/Api.hpp"
#include "prx/libkernel/DirectMemory/DirectMemory.hpp"
#include "prx/libc/include/NativeAotImage.hpp"
#include "prx/libkernel/KernelErrors.hpp"
#include "SceTypes.hpp"
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iterator>
#include <unistd.h>
#include <memory>
#include <mach-o/dyld.h>
#include <mach-o/getsect.h>
#include <mach-o/loader.h>
#include <source_location>
#include <stdexcept>
#include <string>
#include <string_view>

extern "C" {
extern const mach_header_64 _mh_execute_header;
std::uint64_t GuestImageSegmentBytes_nid_no_patch();
}

static void Require(bool condition, std::source_location location = std::source_location::current()) {
    if (!condition) {
        std::fprintf(stderr, "Module info check failed at %s:%u\n", location.file_name(), static_cast<unsigned>(location.line()));
        std::abort();
    }
}

static int writableData = 1;
[[gnu::noinline]] static int Probe() { return writableData; }

static std::uint64_t Address(const void* pointer) {
    return reinterpret_cast<std::uintptr_t>(pointer);
}

static const ModuleSegmentInfo* SegmentContaining(const ModuleInfoEx& info, std::uint64_t address) {
    for (std::uint32_t i = 0; i < info.segment_count; ++i)
        if (address >= info.segments[i].address && address - info.segments[i].address < info.segments[i].size) return &info.segments[i];
    return nullptr;
}

static ModuleInfoEx InfoAt(std::uint64_t address) {
    ModuleInfoEx info{};
    Require(sceKernelGetModuleInfoFromAddr(address, 1, &info) == 0);
    return info;
}

static void CheckHostExecutable() {
    const auto info = InfoAt(Address(reinterpret_cast<const void*>(&Probe)));
    char path[4096];
    std::uint32_t pathBytes = sizeof(path);
    Require(_NSGetExecutablePath(path, &pathBytes) == 0);
    const std::string_view full = path;
    Require(info.name == full.substr(full.find_last_of('/') + 1));
    unsigned long textBytes = 0;
    const auto* text = getsegmentdata(&_mh_execute_header, SEG_TEXT, &textBytes);
    Require(text != nullptr && info.segment_count >= 2);
    Require(info.segments[0].address == Address(text) && info.segments[0].address == Address(&_mh_execute_header));
    Require(info.segments[0].size == textBytes && info.segments[0].prot == (1 | 4));
    const auto* code = SegmentContaining(info, Address(reinterpret_cast<const void*>(&Probe)));
    const auto* data = SegmentContaining(info, Address(&writableData));
    Require(code == &info.segments[0] && data != nullptr && data != code && data->prot == (1 | 2));
    for (std::uint32_t i = 0; i < info.segment_count; ++i) Require(info.segments[i].size != 0 && info.segments[i].prot != 0);
    unsigned long linkeditBytes = 0;
    const auto* linkedit = getsegmentdata(&_mh_execute_header, SEG_LINKEDIT, &linkeditBytes);
    Require(linkedit != nullptr && SegmentContaining(info, Address(linkedit)) == nullptr);

    KernelModule handles[4]{};
    std::size_t actual = 0;
    Require(sceKernelGetModuleList(handles, std::size(handles), &actual) == 0 && actual == 1);
    Require(handles[0] == info.id && handles[0] == sceKernelGetExecutableModuleHandle());
    std::size_t titleActual = 0;
    KernelModule titleHandles[4]{};
    Require(sceKernelGetModuleList2(titleHandles, std::size(titleHandles), &titleActual) == 0 && titleActual == 1 && titleHandles[0] == info.id);
    Require(sceKernelGetModuleList(handles, 0, &actual) == SCE_KERNEL_ERROR_ENOMEM);
    Require(sceKernelGetModuleList(nullptr, 1, &actual) == SCE_KERNEL_ERROR_EFAULT);
    Require(sceKernelGetModuleList(handles, std::size(handles), nullptr) == SCE_KERNEL_ERROR_EFAULT);

    ModuleInfoEx flagged{};
    Require(sceKernelGetModuleInfoFromAddr(Address(reinterpret_cast<const void*>(&Probe)), 2, &flagged) == 0 && flagged.id == info.id);
    Require(sceKernelGetModuleInfoFromAddr(Address(reinterpret_cast<const void*>(&Probe)), 3, &flagged) == SCE_KERNEL_ERROR_EINVAL);
    Require(flagged.segment_count == 0);
    Require(sceKernelGetModuleInfoFromAddr(Address(reinterpret_cast<const void*>(&Probe)), 1, nullptr) == SCE_KERNEL_ERROR_EFAULT);

    void* location = nullptr;
    std::size_t locationBytes = 0;
    Require(sceKernelGetLibkernelTextLocation_nid_postfix(&location, &locationBytes) == 0);
    Require(Address(location) == info.segments[0].address && locationBytes == info.segments[0].size);
    const auto rejects = [](auto call) {
        try { call(); }
        catch (const std::invalid_argument&) { return true; }
        return false;
    };
    Require(rejects([&] { sceKernelGetLibkernelTextLocation_nid_postfix(nullptr, &locationBytes); }));
    Require(rejects([&] { sceKernelGetLibkernelTextLocation_nid_postfix(&location, nullptr); }));
    Require(rejects([] { sceKernelGetModuleInfoFromAddr(0, 3, nullptr); }));

    ModuleInfo plain{};
    Require(sceKernelGetModuleInfo(info.id, nullptr) == SCE_KERNEL_ERROR_EFAULT);
    Require(sceKernelGetModuleInfo(info.id, &plain) == SCE_KERNEL_ERROR_EINVAL);
    plain.st_size = sizeof(plain);
    Require(sceKernelGetModuleInfo(info.id, &plain) == 0 && std::string_view(plain.name) == info.name);
    Require(plain.segment_count == info.segment_count && plain.segments[0].address == info.segments[0].address);
    Require(sceKernelGetModuleInfo2(info.id, &plain) == 0);
    Require(sceKernelGetModuleInfo(info.id + 1000, &plain) == SCE_KERNEL_ERROR_ESRCH);
}

static void CheckOutsideAddresses() {
    ModuleInfoEx info{};
    info.st_size = 7;
    Require(sceKernelGetModuleInfoFromAddr(0, 1, &info) == SCE_KERNEL_ERROR_ESRCH);
    Require(info.st_size == 0 && info.segment_count == 0);
    int local = 0;
    Require(sceKernelGetModuleInfoFromAddr(Address(&local), 1, &info) == SCE_KERNEL_ERROR_ESRCH);
    const std::unique_ptr<char> heap(new char);
    Require(sceKernelGetModuleInfoFromAddr(Address(heap.get()), 1, &info) == SCE_KERNEL_ERROR_ESRCH);
    const auto library = Address(reinterpret_cast<const void*>(&getpid));
    ModuleInfoEx system{};
    Require(sceKernelGetModuleInfoFromAddr(library, 1, &system) == 0 && system.id != InfoAt(Address(reinterpret_cast<const void*>(&Probe))).id);
    Require(sceKernelGetModuleInfoFromAddr(library, 2, &system) == SCE_KERNEL_ERROR_ESRCH);
}

static void CheckGuestSegmentBytes() {
    constexpr std::uint64_t page = PS5_PAGE_SIZE;
    constexpr std::uint32_t noteType = 4;
    const auto header = [](std::uint32_t type, std::uint32_t flags, std::uint64_t offset, std::uint64_t address, std::uint64_t bytes) {
        return Elf64_Phdr{type, flags, offset, address, address, bytes, bytes, PS5_PAGE_SIZE};
    };
    const std::array<Elf64_Phdr, 9> headers{
        header(PT_LOAD, PF_R | PF_X, page, page + 0x100, page),
        header(PT_LOAD, PF_R | PF_W, 4 * page, 4 * page, 8 * page),
        header(PT_LOAD, PF_X, 12 * page, 12 * page, page),
        header(PT_LOAD, PF_W, 24 * page, 24 * page, page),
        header(PT_LOAD, 0, 14 * page, 14 * page, page),
        header(PT_LOAD, PF_W | PF_X, 16 * page, 16 * page, page),
        header(PT_LOAD, PF_R | PF_W | PF_X, 18 * page, 18 * page, page),
        header(PT_LOAD, PF_R, 0, 20 * page, page),
        header(noteType, PF_R, 22 * page, 22 * page, page),
    };
    std::array<std::uint64_t, 8> process{};
    std::array<std::uint64_t, 7> libc{};
    std::array<std::uint64_t, 15> replacement{};
    process[0] = sizeof(process);
    process[1] = 0x4942524f;
    process[7] = reinterpret_cast<std::uint64_t>(libc.data());
    libc[0] = sizeof(libc);
    libc[6] = reinterpret_cast<std::uint64_t>(replacement.data());
    replacement[0] = sizeof(replacement);
    replacement[1] = 2;
    const NativeAotDataRange ranges[]{{process.data(), sizeof(process)}, {libc.data(), sizeof(libc)}, {replacement.data(), sizeof(replacement)}};
    const NativeAotImage image{2, ranges, 3, nullptr, 0, process.data(), sizeof(process), headers.data(), headers.size()};
    const auto before = GuestImageSegmentBytes_nid_no_patch();
    NativeAotRegisterImage_nid_no_patch(&image);
    Require(GuestImageSegmentBytes_nid_no_patch() - before == 2 * page + 8 * page + page + page);
}

int main() {
    Require(Probe() == 1);
    CheckHostExecutable();
    CheckOutsideAddresses();
    CheckGuestSegmentBytes();
}
