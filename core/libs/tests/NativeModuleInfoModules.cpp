#include "prx/libkernel/include/Api.hpp"
#include "prx/libc/include/General.hpp"
#include "prx/libc/include/specifics/linux/ElfTypes.hpp"
#include "prx/libkernel/DirectMemory/DirectMemory.hpp"
#include "prx/libkernel/KernelErrors.hpp"
#include "SceTypes.hpp"
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <filesystem>
#include <initializer_list>
#include <iterator>
#include <mach-o/dyld.h>
#include <mach-o/getsect.h>
#include <mach-o/loader.h>
#include <source_location>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

static void Require(bool condition, std::source_location location = std::source_location::current()) {
    if (!condition) {
        std::fprintf(stderr, "Module info module check failed at %s:%u\n", location.file_name(), static_cast<unsigned>(location.line()));
        std::abort();
    }
}

struct Loaded {
    void* handle;
    const void* code;
    const mach_header_64* header;
    std::uint64_t address;
};

static std::filesystem::path FixturePath(const char* file) {
    return std::filesystem::path(NATIVE_MODULE_INFO_FIXTURE_DIR) / file;
}

static Loaded Describe(void* handle, bool throughGuestLoader) {
    Require(handle != nullptr);
    const void* code = throughGuestLoader ? dlsym_nid_postfix(handle, "NativeModuleInfoFixtureCode") : dlsym(handle, "NativeModuleInfoFixtureCode");
    Require(code != nullptr);
    Dl_info symbol{};
    Require(dladdr(code, &symbol) != 0);
    return {handle, code, static_cast<const mach_header_64*>(symbol.dli_fbase), reinterpret_cast<std::uintptr_t>(code)};
}

static Loaded LoadThroughGuestLoader(const char* file) {
    AddPathAlias_nid_no_patch("module_info_fixtures", NATIVE_MODULE_INFO_FIXTURE_DIR);
    void* handle = dlopen_nid_postfix((std::string("/module_info_fixtures/") + file).c_str(), 2);
    if (!handle) std::fprintf(stderr, "Cannot load %s: %s\n", file, dlerror_nid_postfix());
    return Describe(handle, true);
}

static std::filesystem::path CopyDirectory() {
    return std::filesystem::current_path() / "module_info_modules_copies";
}

static Loaded LoadCopy(const char* fixture, const char* copyName) {
    std::filesystem::create_directories(CopyDirectory());
    const auto copy = CopyDirectory() / copyName;
    std::filesystem::copy_file(FixturePath(fixture), copy, std::filesystem::copy_options::overwrite_existing);
    return Describe(dlopen(copy.c_str(), RTLD_NOW | RTLD_LOCAL), false);
}

static ModuleInfoEx InfoAt(const Loaded& module, int flags = 1, int expected = 0) {
    ModuleInfoEx info{};
    Require(sceKernelGetModuleInfoFromAddr(module.address, flags, &info) == expected);
    return info;
}

static std::vector<KernelModule> ModuleList(bool titleOnly) {
    KernelModule handles[16]{};
    std::size_t actual = 0;
    Require((titleOnly ? sceKernelGetModuleList2 : sceKernelGetModuleList)(handles, std::size(handles), &actual) == 0);
    Require(actual <= std::size(handles));
    return {handles, handles + actual};
}

static bool Contains(const std::vector<KernelModule>& list, KernelModule id) {
    return std::find(list.begin(), list.end(), id) != list.end();
}

static const std::uint8_t* Meta(const Loaded& module, unsigned long* size) {
    return reinterpret_cast<const std::uint8_t*>(getsectiondata(module.header, "__APS5DATA", "__meta", size));
}

static void WriteMeta(const Loaded& module, std::uint64_t version, std::uint64_t loadBias, std::uint64_t count,
                      std::initializer_list<Elf64_Phdr> headers) {
    unsigned long size = 0;
    auto* meta = const_cast<std::uint8_t*>(Meta(module, &size));
    Require(meta != nullptr && size == 0x60 + 3 * sizeof(Elf64_Phdr));
    std::memset(meta, 0, size);
    std::memcpy(meta, &version, sizeof(version));
    std::memcpy(meta + 0x08, &loadBias, sizeof(loadBias));
    std::memcpy(meta + 0x58, &count, sizeof(count));
    std::size_t index = 0;
    for (const auto& header : headers) std::memcpy(meta + 0x60 + index++ * sizeof(header), &header, sizeof(header));
}

static Elf64_Phdr Header(std::uint32_t type, std::uint64_t vaddr, std::uint64_t bytes) {
    return Elf64_Phdr{type, PF_R, 0, vaddr, vaddr, bytes, bytes, PS5_PAGE_SIZE};
}

static void CheckGuestModule(const Loaded& guest) {
    const auto info = InfoAt(guest);
    Require(std::string_view(info.name) == "module_info_guest");

    const char* const names[] = {SEG_TEXT, "__DATA_CONST", SEG_DATA, "__APS5DATA"};
    std::uint32_t present = 0;
    for (const char* name : names) {
        unsigned long bytes = 0;
        const auto* data = getsegmentdata(guest.header, name, &bytes);
        if (!data) continue;
        ++present;
        const auto* reported = std::find_if(info.segments, info.segments + info.segment_count,
            [&](const ModuleSegmentInfo& segment) { return segment.address == reinterpret_cast<std::uintptr_t>(data); });
        Require(reported != info.segments + info.segment_count && reported->size == bytes);
        Require(reported->prot == (std::string_view(name) == SEG_TEXT ? 5 : 3));
    }
    Require(present >= 3 && info.segment_count == present);
    unsigned long linkeditBytes = 0;
    Require(getsegmentdata(guest.header, SEG_LINKEDIT, &linkeditBytes) != nullptr);

    unsigned long frameBytes = 0;
    const auto* frames = getsectiondata(guest.header, SEG_TEXT, "__eh_frame", &frameBytes);
    Require(frames != nullptr && frameBytes == NATIVE_MODULE_INFO_EH_FRAME_BYTES);
    Require(info.eh_frame_addr == reinterpret_cast<std::uintptr_t>(frames) && info.eh_frame_size == frameBytes);
    Require(info.eh_frame_hdr_addr == 0 && info.eh_frame_hdr_size == 0);
}

static void CheckDescribedHeaders(const Loaded& guest) {
    constexpr std::uint64_t bias = 0x10000000;
    const auto hdr = [&] { return InfoAt(guest); };
    const auto none = [&](const ModuleInfoEx& info) { return info.eh_frame_hdr_addr == 0 && info.eh_frame_hdr_size == 0; };

    WriteMeta(guest, 2, bias, 3, {Header(PT_LOAD, 0x1000, 0x100), Header(PT_GNU_EH_FRAME, 0x4000, 0x2345), Header(PT_GNU_EH_FRAME, 0x8000, 0x77)});
    auto info = hdr();
    Require(info.eh_frame_hdr_addr == bias + 0x4000 && info.eh_frame_hdr_size == 0x2345);

    WriteMeta(guest, 1, bias, 3, {Header(PT_LOAD, 0x1000, 0x100), Header(PT_GNU_EH_FRAME, 0x4000, 0x2345)});
    Require(none(hdr()));
    WriteMeta(guest, 2, bias, 4, {Header(PT_LOAD, 0x1000, 0x100), Header(PT_GNU_EH_FRAME, 0x4000, 0x2345)});
    Require(none(hdr()));
    WriteMeta(guest, 2, bias, 3, {Header(PT_LOAD, 0x1000, 0x100), Header(PT_LOAD, 0x2000, 0x100), Header(PT_LOAD, 0x3000, 0x100)});
    Require(none(hdr()));
    WriteMeta(guest, 2, bias, 2, {Header(PT_LOAD, 0x1000, 0x100), Header(PT_LOAD, 0x2000, 0x100), Header(PT_GNU_EH_FRAME, 0x4000, 0x2345)});
    Require(none(hdr()));

    WriteMeta(guest, 2, bias, 1, {Header(PT_GNU_EH_FRAME, 0x4000, 0xffffffff)});
    Require(hdr().eh_frame_hdr_size == 0xffffffff);
    WriteMeta(guest, 2, bias, 1, {Header(PT_GNU_EH_FRAME, 0x4000, std::uint64_t{1} << 32)});
    try {
        InfoAt(guest);
        Require(false);
    } catch (const std::runtime_error& error) {
        Require(std::string_view(error.what()).find("eh_frame_hdr size exceeds 32 bits") != std::string_view::npos);
    }
    WriteMeta(guest, 0, 0, 0, {});
}

static void CheckRelinked(const Loaded& relinked) {
    const auto info = InfoAt(relinked);
    unsigned long textBytes = 0;
    Require(getsegmentdata(relinked.header, SEG_TEXT, &textBytes) != nullptr);
    const char* const names[] = {"__ELF", "__ELF1", "__ELF2", "__ELF3", "__ELF4", "__ELF5"};
    Require(info.segment_count == std::size(info.segments));
    for (std::uint32_t i = 0; i < info.segment_count; ++i) {
        bool matched = false;
        for (const char* name : names) {
            unsigned long bytes = 0;
            const auto* segment = getsegmentdata(relinked.header, name, &bytes);
            Require(segment != nullptr);
            if (info.segments[i].address != reinterpret_cast<std::uintptr_t>(segment)) continue;
            Require(info.segments[i].size == bytes && info.segments[i].prot == 3);
            matched = true;
        }
        Require(matched);
        for (std::uint32_t j = 0; j < i; ++j) Require(info.segments[j].address != info.segments[i].address);
    }
    Require(std::string_view(info.name) == "module_info_relinked");
    unsigned long frameBytes = 0;
    Require(getsectiondata(relinked.header, SEG_TEXT, "__eh_frame", &frameBytes) == nullptr);
    Require(info.eh_frame_addr == 0 && info.eh_frame_size == 0);
}

static void Unload(const Loaded& module, const char* copyName) {
    Require(dlclose(module.handle) == 0);
    std::filesystem::remove(CopyDirectory() / copyName);
}

static void CheckNameStripping() {
    const auto exact = LoadCopy("module_info_guest.guest.prx", ".guest.prx");
    const auto stem = LoadCopy("module_info_guest.guest.prx", "x.guest.prx");
    const auto doubled = LoadCopy("module_info_guest.guest.prx", "x.guest.prx.prx");
    const auto foreign = LoadCopy("module_info_guest.guest.prx", "foreign.dylib");
    const auto exactInfo = InfoAt(exact);
    const auto stemInfo = InfoAt(stem);
    const auto doubledInfo = InfoAt(doubled);
    const auto foreignInfo = InfoAt(foreign);
    Require(std::string_view(exactInfo.name) == ".guest.prx");
    Require(std::string_view(stemInfo.name) == "x");
    Require(std::string_view(doubledInfo.name) == "x.guest.prx.prx");
    Require(std::string_view(foreignInfo.name) == "foreign.dylib");

    const auto all = ModuleList(false);
    const auto title = ModuleList(true);
    for (const auto id : {exactInfo.id, stemInfo.id, doubledInfo.id}) Require(Contains(all, id));
    Require(Contains(title, exactInfo.id) && Contains(title, stemInfo.id) && !Contains(title, doubledInfo.id));
    Require(!Contains(all, foreignInfo.id) && !Contains(title, foreignInfo.id));
    InfoAt(doubled, 2, SCE_KERNEL_ERROR_ESRCH);
    InfoAt(stem, 2);

    Unload(exact, ".guest.prx");
    Unload(stem, "x.guest.prx");
    Unload(doubled, "x.guest.prx.prx");
    Unload(foreign, "foreign.dylib");
}

static void CheckSystemFilter(const Loaded& guest, const Loaded& relinked, const Loaded& system) {
    const auto guestId = InfoAt(guest).id;
    const auto relinkedId = InfoAt(relinked).id;
    const auto info = InfoAt(system);
    Require(std::string_view(info.name) == "module_info_system.prx");
    const auto executable = sceKernelGetExecutableModuleHandle();

    auto all = ModuleList(false);
    Require(all.size() == 4 && all.front() == executable);
    Require(Contains(all, guestId) && Contains(all, relinkedId) && Contains(all, info.id));
    auto title = ModuleList(true);
    Require(title.size() == 3 && title.front() == executable);
    Require(Contains(title, guestId) && Contains(title, relinkedId) && !Contains(title, info.id));

    Require(InfoAt(guest, 2).id == guestId);
    Require(InfoAt(system, 2, SCE_KERNEL_ERROR_ESRCH).segment_count == 0);
    ModuleInfo plain{};
    plain.st_size = sizeof(plain);
    Require(sceKernelGetModuleInfo(info.id, &plain) == 0 && std::string_view(plain.name) == "module_info_system.prx");
    Require(sceKernelGetModuleInfo2(info.id, &plain) == SCE_KERNEL_ERROR_EPERM);
    ModuleInfo titleInfo{};
    titleInfo.st_size = sizeof(titleInfo);
    Require(sceKernelGetModuleInfo2(guestId, &titleInfo) == 0 && std::string_view(titleInfo.name) == "module_info_guest");
}

static void CheckSegmentTooLarge() {
    const auto big = Describe(dlopen(FixturePath("module_info_big.prx").c_str(), RTLD_NOW | RTLD_LOCAL), false);
    ModuleInfoEx info{};
    try {
        sceKernelGetModuleInfoFromAddr(big.address, 1, &info);
        Require(false);
    } catch (const std::runtime_error& error) {
        Require(std::string_view(error.what()).find("segment size exceeds 32 bits") != std::string_view::npos);
    }
    Require(dlclose(big.handle) == 0);
}

int main() {
    std::filesystem::remove_all(CopyDirectory());
    const auto guest = LoadThroughGuestLoader("module_info_guest.guest.prx");
    CheckGuestModule(guest);
    CheckDescribedHeaders(guest);
    const auto relinked = LoadThroughGuestLoader("module_info_relinked.guest.prx");
    CheckRelinked(relinked);
    const auto system = LoadThroughGuestLoader("module_info_system.prx");
    CheckSystemFilter(guest, relinked, system);
    Require(dlclose_nid_postfix(system.handle) == 0);
    Require(dlclose_nid_postfix(relinked.handle) == 0);
    CheckNameStripping();
    CheckSegmentTooLarge();
    Require(dlclose_nid_postfix(guest.handle) == 0);
    std::filesystem::remove_all(CopyDirectory());
}
