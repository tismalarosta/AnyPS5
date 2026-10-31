#ifndef CORE_LIBS_PRX_LIBSCEVIDEOOUT_WINDOWTITLEPACING_HPP
#define CORE_LIBS_PRX_LIBSCEVIDEOOUT_WINDOWTITLEPACING_HPP

#include <chrono>
#include <cstdint>

class WindowTitlePacer {
public:
    using Clock = std::chrono::steady_clock;
    static constexpr std::chrono::seconds Interval{2};

    bool Frame(Clock::time_point now) {
        ++frames;
        if (!started) {
            started = true;
            windowStart = now;
            return true;
        }
        if (now - windowStart < Interval) return false;
        fps = static_cast<double>(frames) / std::chrono::duration<double>(now - windowStart).count();
        windowStart = now;
        frames = 0;
        return true;
    }

    double Fps() const {
        return fps;
    }

private:
    bool started = false;
    Clock::time_point windowStart{};
    std::uint64_t frames = 0;
    double fps = 0.0;
};

#endif
