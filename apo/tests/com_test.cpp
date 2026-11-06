// Drives the APO the way audiodg does: aggregated creation, Initialize, LockForProcess with a real
// media type, APOProcess, Unlock, Release. Builds apo.cpp in directly with a Local\ ring name so it
// runs as a normal user (creating Global\ objects needs a service or admin).
#define SB_RING_PREFIX L"Local\\SoundboardApoComTest"
#include "../src/apo.cpp"

#include <cmath>
#include <cstdio>

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); ++failures; } } while (0)

// Stands in for audiodg's outer object: keeps the inner IUnknown and forwards lookups to it.
struct Outer final : IUnknown {
    IUnknown* inner = nullptr;
    LONG refs = 1;
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (riid == __uuidof(IUnknown)) { *ppv = this; AddRef(); return S_OK; }
        return inner->QueryInterface(riid, ppv);
    }
    STDMETHODIMP_(ULONG) AddRef() override { return ULONG(++refs); }
    STDMETHODIMP_(ULONG) Release() override { return ULONG(--refs); }
};

// The endpoint's property store, as audiodg passes it: only the endpoint GUID matters to us.
struct FakeEndpointStore final : IPropertyStore {
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (riid == __uuidof(IUnknown) || riid == __uuidof(IPropertyStore)) { *ppv = this; return S_OK; }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return 2; }
    STDMETHODIMP_(ULONG) Release() override { return 1; }
    STDMETHODIMP GetCount(DWORD* n) override { *n = 1; return S_OK; }
    STDMETHODIMP GetAt(DWORD, PROPERTYKEY*) override { return E_NOTIMPL; }
    STDMETHODIMP GetValue(REFPROPERTYKEY key, PROPVARIANT* v) override {
        PropVariantInit(v);
        if (key.fmtid != kEndpointGuidKey.fmtid || key.pid != kEndpointGuidKey.pid) return S_OK;  // VT_EMPTY
        const wchar_t guid[] = L"{552C99D7-3A86-46FD-89BA-6E88C24FE4E8}";  // Windows may hand it over in caps
        v->vt = VT_LPWSTR;
        v->pwszVal = static_cast<LPWSTR>(CoTaskMemAlloc(sizeof(guid)));
        memcpy(v->pwszVal, guid, sizeof(guid));
        return S_OK;
    }
    STDMETHODIMP SetValue(REFPROPERTYKEY, REFPROPVARIANT) override { return E_NOTIMPL; }
    STDMETHODIMP Commit() override { return E_NOTIMPL; }
};

static const wchar_t kTestRing[] = L"Local\\SoundboardApoComTest.{552c99d7-3a86-46fd-89ba-6e88c24fe4e8}";

int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);

    IClassFactory* factory = nullptr;
    CHECK(SUCCEEDED(DllGetClassObject(CLSID_SoundboardApo, __uuidof(IClassFactory), reinterpret_cast<void**>(&factory))));

    Outer outer;
    void* bad = nullptr;
    CHECK(factory->CreateInstance(&outer, __uuidof(IAudioProcessingObject), &bad) == CLASS_E_NOAGGREGATION);
    CHECK(SUCCEEDED(factory->CreateInstance(&outer, __uuidof(IUnknown), reinterpret_cast<void**>(&outer.inner))));
    CHECK(outer.inner != nullptr);
    if (!outer.inner) return 1;

    IAudioProcessingObject* apo = nullptr;
    IAudioProcessingObjectRT* rt = nullptr;
    IAudioProcessingObjectConfiguration* config = nullptr;
    IAudioSystemEffects2* fx = nullptr;
    CHECK(SUCCEEDED(outer.QueryInterface(__uuidof(IAudioProcessingObject), reinterpret_cast<void**>(&apo))));
    CHECK(SUCCEEDED(outer.QueryInterface(__uuidof(IAudioProcessingObjectRT), reinterpret_cast<void**>(&rt))));
    CHECK(SUCCEEDED(outer.QueryInterface(__uuidof(IAudioProcessingObjectConfiguration), reinterpret_cast<void**>(&config))));
    CHECK(SUCCEEDED(outer.QueryInterface(__uuidof(IAudioSystemEffects2), reinterpret_cast<void**>(&fx))));
    IUnknown* identity = nullptr;
    apo->QueryInterface(__uuidof(IUnknown), reinterpret_cast<void**>(&identity));
    CHECK(identity == &outer);  // an aggregated object's interfaces report the outer identity
    identity->Release();

    APO_REG_PROPERTIES* props = nullptr;
    CHECK(SUCCEEDED(apo->GetRegistrationProperties(&props)) && props && props->clsid == CLSID_SoundboardApo);
    CoTaskMemFree(props);

    APOInitSystemEffects2 init{};
    init.APOInit.cbSize = sizeof(init);
    init.APOInit.clsid = CLSID_SoundboardApo;
    FakeEndpointStore store;
    init.pAPOEndpointProperties = &store;
    CHECK(SUCCEEDED(apo->Initialize(sizeof(init), reinterpret_cast<BYTE*>(&init))));

    HANDLE map = OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, kTestRing);  // what the app gets
    CHECK(map != nullptr);
    if (!map) return 1;
    auto* view = static_cast<uint8_t*>(MapViewOfFile(map, FILE_MAP_WRITE, 0, 0, sb::RingBytes(sb::kRingCapacity)));
    auto* h = reinterpret_cast<sb::RingHeader*>(view);
    CHECK(h->magic == sb::kRingMagic && h->version == 2 && h->rate == 0);

    // A mono 44.1 kHz float mic.
    UNCOMPRESSEDAUDIOFORMAT format{};
    format.guidFormatType = KSDATAFORMAT_SUBTYPE_IEEE_FLOAT;
    format.dwSamplesPerFrame = 1;
    format.dwBytesPerSampleContainer = 4;
    format.dwValidBitsPerSample = 32;
    format.fFramesPerSecond = 44100.f;
    format.dwChannelMask = SPEAKER_FRONT_CENTER;
    IAudioMediaType* media = nullptr;
    CHECK(SUCCEEDED(CreateAudioMediaTypeFromUncompressedAudioFormat(&format, &media)));
    IAudioMediaType* supported = nullptr;
    CHECK(apo->IsInputFormatSupported(media, media, &supported) == S_OK);
    if (supported) supported->Release();

    constexpr UINT32 kFrames = 441;
    float buffer[kFrames] = {};
    APO_CONNECTION_DESCRIPTOR desc{};
    desc.Type = APO_CONNECTION_BUFFER_TYPE_EXTERNAL;
    desc.pBuffer = reinterpret_cast<UINT_PTR>(buffer);
    desc.u32MaxFrameCount = kFrames;
    desc.pFormat = media;
    desc.u32Signature = APO_CONNECTION_DESCRIPTOR_SIGNATURE;
    APO_CONNECTION_DESCRIPTOR* descs[] = {&desc};
    CHECK(SUCCEEDED(config->LockForProcess(1, descs, 1, descs)));
    CHECK(h->rate == 44100);
    CHECK(h->consumer == GetCurrentProcessId());

    // The app queues 100 stereo frames.
    auto* samples = reinterpret_cast<float*>(view + sb::kHeaderSize);
    for (int i = 0; i < 100; ++i) { samples[2 * i] = 0.2f; samples[2 * i + 1] = 0.4f; }
    h->write_pos = 100;

    APO_CONNECTION_PROPERTY prop{};
    prop.pBuffer = reinterpret_cast<UINT_PTR>(buffer);
    prop.u32ValidFrameCount = kFrames;
    prop.u32BufferFlags = BUFFER_SILENT;
    prop.u32Signature = APO_CONNECTION_PROPERTY_SIGNATURE;
    for (float& s : buffer) s = 123.f;  // a silent buffer's contents are garbage
    APO_CONNECTION_PROPERTY* props_[] = {&prop};
    rt->APOProcess(1, props_, 1, props_);
    CHECK(prop.u32BufferFlags == BUFFER_VALID);
    CHECK(prop.u32ValidFrameCount == kFrames);
    CHECK(std::fabs(buffer[0] - 0.3f) < 1e-6f && std::fabs(buffer[99] - 0.3f) < 1e-6f && buffer[100] == 0.f);
    CHECK(h->read_pos == 100);
    CHECK(h->heartbeat != 0);

    // Nothing queued: the mic passes through untouched.
    for (float& s : buffer) s = 0.1f;
    prop.u32BufferFlags = BUFFER_VALID;
    rt->APOProcess(1, props_, 1, props_);
    CHECK(buffer[0] == 0.1f && buffer[kFrames - 1] == 0.1f && prop.u32BufferFlags == BUFFER_VALID);

    CHECK(SUCCEEDED(config->UnlockForProcess()));
    CHECK(h->rate == 0 && h->consumer == 0);

    UINT count = 7;
    GUID* ids = reinterpret_cast<GUID*>(1);
    CHECK(SUCCEEDED(fx->GetEffectsList(&ids, &count, nullptr)) && count == 0 && ids == nullptr);

    fx->Release();
    config->Release();
    rt->Release();
    apo->Release();
    CHECK(outer.refs == 1);  // every interface reference went back to the outer object
    media->Release();
    CHECK(DllCanUnloadNow() == S_FALSE);
    outer.inner->Release();  // the outer object lets go of the inner one: the APO is destroyed
    CHECK(DllCanUnloadNow() == S_OK);

    UnmapViewOfFile(view);
    CloseHandle(map);
    std::printf(failures ? "%d failure(s)\n" : "COM tests passed\n", failures);
    return failures ? 1 : 0;
}
