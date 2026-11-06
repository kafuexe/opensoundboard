// The shared-memory ring between the Soundboard app (producer) and this plugin (consumer).
// Layout and rules: docs/mic-bridge.md. Header-only and free of Windows APIs so tests/ring_test.cpp
// can exercise it outside audiodg.
#pragma once

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace sb {

constexpr uint32_t kRingMagic = 0x524D4253;  // "SBMR"
constexpr uint32_t kRingVersion = 2;
constexpr uint32_t kRingChannels = 2;        // always interleaved stereo; the plugin maps to the mic's layout
constexpr uint32_t kRingCapacity = 96000;    // frames: 2 s at 48 kHz, 0.5 s at 192 kHz
constexpr uint32_t kHeaderSize = 64;

struct RingHeader {
    uint32_t magic;        // written last when the ring is created
    uint32_t version;
    uint32_t rate;         // mic's frame rate while processing, 0 when the mic isn't running
    uint32_t channels;     // kRingChannels
    uint32_t capacity;     // frames
    uint32_t consumer;     // pid of the audiodg that reads the ring, 0 = nobody
    uint64_t write_pos;    // total frames written (app)
    uint64_t read_pos;     // total frames read (plugin)
    uint64_t heartbeat;    // GetTickCount64() of the last APOProcess (plugin)
    uint64_t owner;        // (pid << 32) | instance of the plugin instance reading the ring, 0 = nobody
    uint8_t reserved[8];
};
static_assert(sizeof(RingHeader) == kHeaderSize);
static_assert(offsetof(RingHeader, write_pos) == 24 && offsetof(RingHeader, read_pos) == 32 &&
              offsetof(RingHeader, heartbeat) == 40 && offsetof(RingHeader, owner) == 48);

constexpr size_t RingBytes(uint32_t capacity) { return kHeaderSize + size_t(capacity) * kRingChannels * sizeof(float); }

inline std::atomic_ref<uint64_t> At(uint64_t& v) { return std::atomic_ref<uint64_t>(v); }
inline std::atomic_ref<uint32_t> At(uint32_t& v) { return std::atomic_ref<uint32_t>(v); }

// Fill in a freshly created (zeroed) ring. Magic goes last so the app never sees a half-written header.
inline void InitRing(void* base, uint32_t capacity) {
    auto* h = static_cast<RingHeader*>(base);
    h->version = kRingVersion;
    h->rate = 0;
    h->channels = kRingChannels;
    h->capacity = capacity;
    At(h->write_pos).store(0);
    At(h->read_pos).store(0);
    At(h->magic).store(kRingMagic, std::memory_order_release);
}

// A ring that already existed (the app held it open across an audiodg restart) is reusable only
// if it has our layout.
inline bool RingLooksValid(const void* base, uint32_t capacity) {
    auto* h = static_cast<const RingHeader*>(base);
    return h->magic == kRingMagic && h->version == kRingVersion && h->channels == kRingChannels &&
           h->capacity == capacity;
}

// Only one reader may advance read_pos. Windows can create several instances for one mic (one per
// processing mode), all in the same audiodg; the first to start processing reads. An owner from a
// different pid can only be an earlier audiodg (there is one at a time), so it's stale: take over.
inline bool ClaimOwner(void* base, uint32_t pid, uint32_t instance) {
    auto* h = static_cast<RingHeader*>(base);
    const uint64_t mine = (uint64_t(pid) << 32) | instance;
    uint64_t seen = At(h->owner).load();
    for (;;) {
        if (seen == mine) return true;
        if (seen != 0 && uint32_t(seen >> 32) == pid) return false;  // a live sibling instance has it
        if (At(h->owner).compare_exchange_weak(seen, mine)) {
            At(h->consumer).store(pid);
            return true;
        }
    }
}

inline void ReleaseOwner(void* base, uint32_t pid, uint32_t instance) {
    auto* h = static_cast<RingHeader*>(base);
    uint64_t expected = (uint64_t(pid) << 32) | instance;
    if (At(h->owner).compare_exchange_strong(expected, 0)) At(h->consumer).store(0);
}

class RingReader {
public:
    // Keep latency low: if the app got more than this far ahead (e.g. the mic was paused), jump to
    // the newest audio, leaving this much queued.
    static constexpr uint64_t kMaxBacklogMs = 100;
    static constexpr uint64_t kKeepMs = 20;

    explicit RingReader(void* base) : h_(static_cast<RingHeader*>(base)),
        data_(reinterpret_cast<float*>(static_cast<uint8_t*>(base) + kHeaderSize)) {}

    RingHeader* header() const { return h_; }

    // Called when processing starts or the format changes: publish the mic's rate so the app
    // resamples to it, and drop anything queued for the old state.
    void Start(uint32_t rate) {
        DropBacklog();
        At(h_->rate).store(rate, std::memory_order_release);
        rate_ = rate;
    }

    void Stop() { At(h_->rate).store(0, std::memory_order_release); }

    void DropBacklog() { At(h_->read_pos).store(At(h_->write_pos).load(std::memory_order_acquire), std::memory_order_release); }

    void Heartbeat(uint64_t now_ms) { At(h_->heartbeat).store(now_ms, std::memory_order_relaxed); }

    // Copy up to `frames` stereo frames into `out` (interleaved). Returns frames copied.
    // Real-time safe: no locks, no allocation.
    uint32_t Read(float* out, uint32_t frames) {
        const uint32_t cap = h_->capacity;
        const uint64_t w = At(h_->write_pos).load(std::memory_order_acquire);
        uint64_t r = At(h_->read_pos).load(std::memory_order_relaxed);
        uint64_t fill = w - r;
        if (w < r || fill > cap) return 0;  // torn or garbage position from the writer: skip this period
        const uint64_t max_backlog = rate_ * kMaxBacklogMs / 1000;
        if (rate_ && fill > max_backlog) {
            const uint64_t keep = rate_ * kKeepMs / 1000;
            r = w - keep;
            fill = keep;
        }
        const uint32_t n = static_cast<uint32_t>(std::min<uint64_t>(fill, frames));
        const uint32_t start = static_cast<uint32_t>(r % cap);
        const uint32_t first = std::min(n, cap - start);
        std::memcpy(out, data_ + size_t(start) * kRingChannels, size_t(first) * kRingChannels * sizeof(float));
        std::memcpy(out + size_t(first) * kRingChannels, data_, size_t(n - first) * kRingChannels * sizeof(float));
        At(h_->read_pos).store(r + n, std::memory_order_release);
        return n;
    }

private:
    RingHeader* h_;
    float* data_;
    uint64_t rate_ = 0;
};

// Add `frames` interleaved stereo frames to the mic buffer (`channels` per frame).
// Mono mics get (L+R)/2; others get L and R in the first two channels.
inline void MixStereoInto(float* mic, uint32_t channels, const float* stereo, uint32_t frames) {
    auto clamp = [](float v) { return v > 1.f ? 1.f : (v < -1.f ? -1.f : v); };
    for (uint32_t i = 0; i < frames; ++i) {
        float* f = mic + size_t(i) * channels;
        const float l = stereo[2 * i], r = stereo[2 * i + 1];
        if (channels == 1) {
            f[0] = clamp(f[0] + 0.5f * (l + r));
        } else {
            f[0] = clamp(f[0] + l);
            f[1] = clamp(f[1] + r);
        }
    }
}

}  // namespace sb
