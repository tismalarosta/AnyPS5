#ifdef __APPLE__

#include "prx/libc/include/specifics/linux/ElfTypes.hpp"
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <mach-o/getsect.h>
#include <mach-o/loader.h>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

namespace {

constexpr std::uint64_t MetaVersion = 2;
constexpr std::size_t LoadBiasOffset = 0x08;
constexpr std::size_t HeaderCountOffset = 0x58;
constexpr std::size_t HeadersOffset = 0x60;

struct LoadedImage {
    const mach_header_64* header;
    std::intptr_t slide;
    bool guest;
    std::string name;
};

struct GuestImage {
    std::uintptr_t loadBias;
    std::string name;
    std::vector<Elf64_Phdr> headers;
};

std::mutex imagesLock;
std::vector<LoadedImage> images;

void AddImage(const mach_header* image, intptr_t slide) {
    const auto* header = reinterpret_cast<const mach_header_64*>(image);
    if (header == nullptr || header->magic != MH_MAGIC_64 || (header->flags & MH_DYLIB_IN_CACHE) != 0) return;
    unsigned long size = 0;
    const bool guest = getsectiondata(header, "__APS5DATA", "__meta", &size) != nullptr;
    Dl_info info {};
    std::string name = header->filetype != MH_EXECUTE && dladdr(image, &info) != 0 && info.dli_fname != nullptr ? info.dli_fname : "";
    std::lock_guard lock(imagesLock);
    images.push_back({header, slide, guest, std::move(name)});
}

void RemoveImage(const mach_header* image, intptr_t) {
    std::lock_guard lock(imagesLock);
    std::erase_if(images, [image](const LoadedImage& loaded) { return loaded.header == reinterpret_cast<const mach_header_64*>(image); });
}

void RegisterImageCallbacks() {
    [[maybe_unused]] static const bool registered = [] {
        _dyld_register_func_for_remove_image(RemoveImage);
        _dyld_register_func_for_add_image(AddImage);
        return true;
    }();
}

std::vector<GuestImage> GuestImages() {
    RegisterImageCallbacks();
    std::vector<GuestImage> found;
    std::lock_guard lock(imagesLock);
    found.reserve(images.size());
    for (const auto& image : images) {
        if (!image.guest) continue;
        unsigned long size = 0;
        const auto* meta = getsectiondata(image.header, "__APS5DATA", "__meta", &size);
        if (meta == nullptr || size < HeadersOffset) continue;
        std::uint64_t version;
        std::uint64_t loadBias;
        std::uint64_t count;
        std::memcpy(&version, meta, sizeof(version));
        std::memcpy(&loadBias, meta + LoadBiasOffset, sizeof(loadBias));
        std::memcpy(&count, meta + HeaderCountOffset, sizeof(count));
        if (version != MetaVersion || count > 0xffff || count > (size - HeadersOffset) / sizeof(Elf64_Phdr)) continue;
        auto& guest = found.emplace_back(static_cast<std::uintptr_t>(loadBias), image.name, std::vector<Elf64_Phdr>(count));
        std::memcpy(guest.headers.data(), meta + HeadersOffset, count * sizeof(Elf64_Phdr));
    }
    return found;
}

[[maybe_unused]] const bool registeredAtLoad = (RegisterImageCallbacks(), true);

}

extern "C" int ForEachMachImage_nid_no_patch(int (*visit)(const mach_header_64*, std::intptr_t, void*), void* data) {
    RegisterImageCallbacks();
    std::lock_guard lock(imagesLock);
    for (const auto& image : images) {
        if (const int result = visit(image.header, image.slide, data); result != 0) return result;
    }
    return 0;
}

extern "C" int dl_iterate_phdr(int (*callback)(dl_phdr_info*, std::size_t, void*), void* data) {
    for (const auto& guest : GuestImages()) {
        dl_phdr_info info {};
        info.dlpi_addr = guest.loadBias;
        info.dlpi_name = guest.name.c_str();
        info.dlpi_phdr = guest.headers.data();
        info.dlpi_phnum = static_cast<std::uint16_t>(guest.headers.size());
        if (const int result = callback(&info, sizeof(info), data); result != 0) return result;
    }
    return 0;
}

#endif
