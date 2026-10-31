#include "prx/libSceVideoOut/include/WindowTitlePacing.hpp"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>

namespace {

using namespace std::chrono_literals;

void Require(bool condition, const char* message) {
    if (condition) return;
    std::fprintf(stderr, "window_title_pacing: %s\n", message);
    std::exit(1);
}

void FirstFrameSetsTheTitle() {
    WindowTitlePacer pacer;
    Require(pacer.Frame(WindowTitlePacer::Clock::time_point{} + 1s), "the first frame sets the title");
    Require(pacer.Fps() == 0.0, "no FPS figure exists before the first interval");
}

void TitleFollowsTheFpsInterval() {
    WindowTitlePacer pacer;
    const auto start = WindowTitlePacer::Clock::time_point{} + 1s;
    int updates = 0;
    for (int frame = 0; frame <= 600; ++frame) {
        if (pacer.Frame(start + std::chrono::microseconds(frame * 16667))) ++updates;
    }
    Require(updates >= 5 && updates <= 6, "ten seconds at 60 Hz set the title about once per two seconds, not on every frame");
    Require(std::fabs(pacer.Fps() - 60.0) < 0.5, "the FPS figure measures the frames of the last interval");
}

void SlowFramesStillRefresh() {
    WindowTitlePacer pacer;
    const auto start = WindowTitlePacer::Clock::time_point{} + 1s;
    pacer.Frame(start);
    Require(!pacer.Frame(start + 1s), "a frame inside the interval leaves the title alone");
    Require(pacer.Frame(start + 3s), "a frame after the interval refreshes the title");
    Require(std::fabs(pacer.Fps() - 1.0) < 1e-9, "the FPS figure counts the three frames over the three real seconds");
}

}

int main() {
    FirstFrameSetsTheTitle();
    TitleFollowsTheFpsInterval();
    SlowFramesStillRefresh();
    std::puts("window_title_pacing: ok");
    return 0;
}
