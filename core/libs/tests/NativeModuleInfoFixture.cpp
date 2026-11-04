#include "prx/libc/include/specifics/linux/ElfTypes.hpp"

extern "C" {

[[gnu::used]] int NativeModuleInfoFixtureValue = 1;
[[gnu::used, gnu::noinline]] int NativeModuleInfoFixtureCode() { return NativeModuleInfoFixtureValue; }

}

[[gnu::section("__APS5DATA,__meta"), gnu::used]] alignas(8) unsigned char metadata[0x60 + 3 * sizeof(Elf64_Phdr)]{};

#ifdef NATIVE_MODULE_INFO_FIXTURE_ELF
[[gnu::section("__ELF,__elf"), gnu::used]] unsigned char relinkedSegment[64] = {1};
[[gnu::section("__ELF1,__elf"), gnu::used]] unsigned char relinkedSegment1[64] = {1};
[[gnu::section("__ELF2,__elf"), gnu::used]] unsigned char relinkedSegment2[64] = {1};
[[gnu::section("__ELF3,__elf"), gnu::used]] unsigned char relinkedSegment3[64] = {1};
[[gnu::section("__ELF4,__elf"), gnu::used]] unsigned char relinkedSegment4[64] = {1};
[[gnu::section("__ELF5,__elf"), gnu::used]] unsigned char relinkedSegment5[64] = {1};
#endif

#ifdef NATIVE_MODULE_INFO_FIXTURE_BIG
[[gnu::used]] unsigned char bigSegment[4ull << 30];
#endif
