#ifndef CORE_LIBS_PRX_LIBC_INCLUDE_NATIVEAOTIMAGE_HPP
#define CORE_LIBS_PRX_LIBC_INCLUDE_NATIVEAOTIMAGE_HPP

#include <cstddef>
#include <cstdint>
#include "prx/libc/include/specifics/linux/ElfTypes.hpp"

struct NativeAotDataRange {
    const void* address;
    std::size_t bytes;
};

struct NativeAotImage {
    std::uint64_t version;
    const NativeAotDataRange* ranges;
    std::size_t rangeCount;
    const void* const* functions;
    std::size_t functionCount;
    const void* processParameters;
    std::size_t processParameterBytes;
    const Elf64_Phdr* programHeaders;
    std::size_t programHeaderCount;
};

extern "C" void NativeAotRegisterImage_nid_no_patch(const NativeAotImage* image);
extern "C" std::size_t NativeAotImageProgramHeaders_nid_no_patch(const Elf64_Phdr** headers);
extern "C" void NativeAotRequireReadOnly_nid_no_patch(const NativeAotDataRange* ranges, std::size_t count);

#endif
