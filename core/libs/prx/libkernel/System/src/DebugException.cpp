#include "SceTypes.hpp"
#include "prx/libc/include/general/LogMacros.hpp"

extern "C" {

void APS5_VABI sceKernelDebugRaiseException(int c1, int c2) {
    APS5_LOG_OUT("sceKernelDebugRaiseException c1=0x%08x c2=0x%08x caller=%p", static_cast<unsigned>(c1), static_cast<unsigned>(c2), __builtin_return_address(0));
}

void APS5_VABI sceKernelDebugRaiseExceptionOnReleaseMode(int c1, int c2) {
    APS5_LOG_OUT("sceKernelDebugRaiseExceptionOnReleaseMode c1=0x%08x c2=0x%08x caller=%p", static_cast<unsigned>(c1), static_cast<unsigned>(c2), __builtin_return_address(0));
}

}
