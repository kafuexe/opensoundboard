// Tests for the ring consumer and the stereo mix, compiled as a plain console exe (build.ps1 runs it).
#include <cmath>
#include <cstdio>
#include <vector>

#include "../src/ring.h"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); ++failures; } } while (0)

struct TestRing {
    explicit TestRing(uint32_t capacity) : mem(sb::RingBytes(capacity) / 4 + 1, 0.f) { sb::InitRing(base(), capacity); }
    void* base() { return mem.data(); }
    sb::RingHeader* h() { return static_cast<sb::RingHeader*>(base()); }
    float* data() { return reinterpret_cast<float*>(static_cast<uint8_t*>(base()) + sb::kHeaderSize); }
    // What the app does: samples first, then publish the write position.
    void Write(uint32_t frames, float first_value) {
        for (uint32_t i = 0; i < frames; ++i) {
            uint64_t pos = (h()->write_pos + i) % h()->capacity;
            data()[pos * 2] = first_value + float(i);
            data()[pos * 2 + 1] = -(first_value + float(i));
        }
        h()->write_pos += frames;
    }
    std::vector<float> mem;
};

static void header_layout_matches_the_app() {
    TestRing ring(8);
    CHECK(ring.h()->magic == sb::kRingMagic && ring.h()->version == 2 && ring.h()->channels == 2);
    CHECK(ring.h()->capacity == 8 && ring.h()->rate == 0 && ring.h()->consumer == 0);
    CHECK(sb::RingLooksValid(ring.base(), 8));
    CHECK(!sb::RingLooksValid(ring.base(), 16));
}

static void reads_what_was_written_and_wraps() {
    TestRing ring(8);
    sb::RingReader reader(ring.base());
    reader.Start(48000);
    float out[32];
    ring.Write(6, 1.f);
    CHECK(reader.Read(out, 4) == 4);
    CHECK(out[0] == 1.f && out[1] == -1.f && out[6] == 4.f);
    ring.Write(5, 100.f);  // wraps around the end of the buffer
    CHECK(reader.Read(out, 16) == 7);
    CHECK(out[0] == 5.f && out[2] == 6.f && out[4] == 100.f && out[12] == 104.f && out[13] == -104.f);
    CHECK(reader.Read(out, 16) == 0);  // empty
    CHECK(ring.h()->read_pos == ring.h()->write_pos);
}

static void start_publishes_rate_and_drops_old_audio() {
    TestRing ring(8);
    ring.Write(5, 1.f);
    sb::RingReader reader(ring.base());
    reader.Start(44100);
    CHECK(ring.h()->rate == 44100);
    float out[16];
    CHECK(reader.Read(out, 8) == 0);
    reader.Stop();
    CHECK(ring.h()->rate == 0);
}

static void garbage_positions_read_nothing() {
    TestRing ring(8);
    sb::RingReader reader(ring.base());
    reader.Start(48000);
    float out[16];
    ring.h()->write_pos = 1000;  // more than capacity ahead: torn or bogus
    CHECK(reader.Read(out, 8) == 0);
    ring.h()->read_pos = 2000;  // behind the reader
    CHECK(reader.Read(out, 8) == 0);
}

static void large_backlog_skips_to_recent_audio() {
    TestRing ring(sb::kRingCapacity);
    sb::RingReader reader(ring.base());
    reader.Start(48000);
    ring.Write(48000, 0.f);  // 1 s queued, far past the 100 ms limit
    std::vector<float> out(48000 * 2);
    uint32_t got = reader.Read(out.data(), 48000);
    CHECK(got == 960);                    // kept 20 ms
    CHECK(out[0] == float(48000 - 960));  // ...the newest 20 ms
}

static void owner_claim() {
    TestRing ring(8);
    CHECK(sb::ClaimOwner(ring.base(), 111, 1));
    CHECK(sb::ClaimOwner(ring.base(), 111, 1));   // already ours
    CHECK(!sb::ClaimOwner(ring.base(), 111, 2));  // a sibling instance in the same audiodg: no
    CHECK(ring.h()->consumer == 111);
    CHECK(sb::ClaimOwner(ring.base(), 222, 1));   // a new audiodg means the old one is gone
    CHECK(ring.h()->consumer == 222);
    sb::ReleaseOwner(ring.base(), 111, 1);        // not ours any more
    CHECK(ring.h()->owner == ((uint64_t(222) << 32) | 1));
    sb::ReleaseOwner(ring.base(), 222, 1);
    CHECK(ring.h()->owner == 0 && ring.h()->consumer == 0);
    CHECK(sb::ClaimOwner(ring.base(), 222, 2));   // free again: the sibling can take it
}

static void mix_into_mono_stereo_and_surround() {
    const float stereo[] = {0.5f, 0.1f, 0.8f, 0.8f};
    float mono[] = {0.1f, 0.5f};
    sb::MixStereoInto(mono, 1, stereo, 2);
    CHECK(std::fabs(mono[0] - 0.4f) < 1e-6f && mono[1] == 1.f);  // second frame clamps
    float st[] = {0.f, 0.f, 0.f, 0.f};
    sb::MixStereoInto(st, 2, stereo, 2);
    CHECK(st[0] == 0.5f && st[1] == 0.1f && st[2] == 0.8f);
    float quad[8] = {0, 0, 0.3f, 0.3f, 0, 0, 0.3f, 0.3f};
    sb::MixStereoInto(quad, 4, stereo, 2);
    CHECK(quad[0] == 0.5f && quad[2] == 0.3f && quad[4] == 0.8f && quad[7] == 0.3f);
}

int main() {
    header_layout_matches_the_app();
    reads_what_was_written_and_wraps();
    start_publishes_rate_and_drops_old_audio();
    garbage_positions_read_nothing();
    large_backlog_skips_to_recent_audio();
    owner_claim();
    mix_into_mono_stereo_and_surround();
    std::printf(failures ? "%d failure(s)\n" : "ring tests passed\n", failures);
    return failures ? 1 : 0;
}
