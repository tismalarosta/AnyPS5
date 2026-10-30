#include "prx/libSceLibcInternal/include/Statvfs.hpp"
#include <array>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <source_location>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/un.h>
#include <unistd.h>

extern "C" int statvfs_nid_postfix(const char*, LibcStatvfs*);

extern "C" std::filesystem::path ResolvePath_nid_no_patch(const char* path) {
    return std::filesystem::path(path);
}

extern "C" bool FinalPathComponentIsDot_nid_no_patch(const char* path) {
    return std::filesystem::path(path).filename() == ".";
}

static void Require(bool value, std::source_location location = std::source_location::current()) {
    if (!value) {
        std::fprintf(stderr, "Darwin statvfs check failed at line %u\n", location.line());
        std::abort();
    }
}

static void CheckVolume(const std::filesystem::path& path) {
    std::array<std::uint64_t, 13> bytes;
    bytes.fill(0x5a5a5a5a5a5a5a5aull);
    struct statvfs native{};
    Require(::statvfs(path.c_str(), &native) == 0);
    errno = 12345;
    Require(statvfs_nid_postfix(path.c_str(), reinterpret_cast<LibcStatvfs*>(bytes.data() + 1)) == 0);
    Require(errno == 12345 && bytes.front() == 0x5a5a5a5a5a5a5a5aull && bytes.back() == bytes.front());
    LibcStatvfs result{};
    std::memcpy(&result, bytes.data() + 1, sizeof(result));
    Require(result.f_blocks == native.f_blocks && result.f_bsize == native.f_bsize);
    Require(result.f_frsize == (native.f_frsize ? native.f_frsize : native.f_bsize));
    Require(result.f_bavail <= result.f_bfree && result.f_bfree <= result.f_blocks);
    Require(result.f_ffree == result.f_favail && result.f_fsid == 0 && result.f_namemax == native.f_namemax);
    Require(result.f_flag == (((native.f_flag & ST_RDONLY) ? 1u : 0u) | ((native.f_flag & ST_NOSUID) ? 2u : 0u)));
}

static void CheckError(const char* path, int expected) {
    LibcStatvfs result{};
    std::memset(&result, 0x5a, sizeof(result));
    const auto before = result;
    errno = 0;
    Require(statvfs_nid_postfix(path, &result) == -1);
    Require(errno == expected && std::memcmp(&result, &before, sizeof(result)) == 0);
}

int main() {
    const auto root = std::filesystem::temp_directory_path() / ("statvfs-darwin-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    Require(std::filesystem::create_directory(root));
    const auto file = root / "file";
    { std::ofstream output(file); output << "unchanged"; }
    CheckVolume(root);
    CheckVolume(file);
    Require(::chmod(file.c_str(), 0) == 0);
    CheckVolume(file);
    Require(::chmod(file.c_str(), 0600) == 0);
    const auto fifo = root / "fifo";
    Require(::mkfifo(fifo.c_str(), 0600) == 0);
    CheckVolume(fifo);
    const auto socketPath = root / "socket";
    const int socket = ::socket(AF_UNIX, SOCK_STREAM, 0);
    Require(socket >= 0);
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    const auto name = socketPath.string();
    Require(name.size() < sizeof(address.sun_path));
    std::memcpy(address.sun_path, name.c_str(), name.size() + 1);
    Require(::bind(socket, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) == 0);
    CheckVolume(socketPath);
    Require(::close(socket) == 0);
    Require(std::filesystem::remove(socketPath));
    std::filesystem::create_symlink("file", root / "link");
    CheckVolume(root / "link");
    std::filesystem::create_symlink("missing", root / "dangling");
    std::filesystem::create_symlink("loop", root / "loop");
    CheckError(nullptr, 14);
    CheckError("", 2);
    CheckError((root / "missing").c_str(), 2);
    CheckError((root / "dangling").c_str(), 2);
    CheckError((root / "loop").c_str(), 62);
    CheckError((file.string() + "/").c_str(), 20);
    CheckError((file / ".").c_str(), 20);
    CheckError((file / "child").c_str(), 20);
    const auto blocked = root / "blocked";
    Require(std::filesystem::create_directory(blocked));
    { std::ofstream output(blocked / "file"); output << "unchanged"; }
    Require(::chmod(blocked.c_str(), 0) == 0);
    if (::geteuid() != 0) CheckError((blocked / "file").c_str(), 13);
    Require(::chmod(blocked.c_str(), 0700) == 0);
    Require(std::filesystem::remove_all(blocked) == 2);
    Require(statvfs_nid_postfix(file.c_str(), nullptr) == -1 && errno == 14);
    Require(statvfs_nid_postfix((root / "missing").c_str(), nullptr) == -1 && errno == 2);
    const auto count = [] { return std::distance(std::filesystem::directory_iterator("/dev/fd"), std::filesystem::directory_iterator{}); };
    const auto before = count();
    for (int i = 0; i != 64; ++i) CheckVolume(file);
    Require(count() == before);
    Require(std::filesystem::remove_all(root) == 6);
}
