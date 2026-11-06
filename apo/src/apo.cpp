// SoundboardApo: a capture endpoint effect (EFX) that adds the Soundboard app's audio to the mic.
// Design: docs/dll-spec.md. Ring protocol: docs/mic-bridge.md.

#include <windows.h>
#include <objbase.h>
#include <mmdeviceapi.h>
#include <sddl.h>
#include <audioenginebaseapo.h>
#include <audioengineextensionapo.h>
#include <baseaudioprocessingobject.h>
#include <audiomediatype.h>

#include <atomic>
#include <new>
#include <vector>

#include "log.h"
#include "ring.h"

using sb::Log;

// {6C2825A3-7231-43EA-8D9B-A3B5BCF81B06}
static const CLSID CLSID_SoundboardApo = {0x6c2825a3, 0x7231, 0x43ea, {0x8d, 0x9b, 0xa3, 0xb5, 0xbc, 0xf8, 0x1b, 0x06}};
static const wchar_t kClsidString[] = L"{6C2825A3-7231-43EA-8D9B-A3B5BCF81B06}";
// Each mic gets its own ring: "<prefix>.{endpoint guid}", so the app picks a mic just by opening
// that mic's ring. tests/com_test.cpp builds with a Local\ prefix.
#ifndef SB_RING_PREFIX
#define SB_RING_PREFIX L"Global\\SoundboardMicRing"
#endif

// PKEY_AudioEndpoint_GUID from mmdeviceapi.h, spelled out so we don't need initguid.
static const PROPERTYKEY kEndpointGuidKey = {{0x1da5d803, 0xd492, 0x4edd, {0x8c, 0x23, 0xe0, 0xc0, 0xff, 0xee, 0x7f, 0x0e}}, 4};

static HMODULE g_module;
static std::atomic<LONG> g_objects{0};
static std::atomic<LONG> g_locks{0};

static CRegAPOProperties<5> g_regProperties(
    CLSID_SoundboardApo, L"Soundboard mic", L"Soundboard", 1, 0, __uuidof(IAudioProcessingObject),
    static_cast<APO_FLAG>(APO_FLAG_DEFAULT | APO_FLAG_INPLACE), 1, 1, 1, 1, ULONG_MAX,
    __uuidof(IAudioProcessingObjectRT), __uuidof(IAudioProcessingObjectConfiguration), __uuidof(IAudioSystemEffects),
    __uuidof(IAudioSystemEffects2));

// Distinguishes instances in one audiodg for the ring's owner field.
static std::atomic<uint32_t> g_nextInstance{1};

class SoundboardApo final : public CBaseAudioProcessingObject, public IAudioSystemEffects2 {
public:
    // The non-delegating IUnknown. audiodg creates us aggregated (with an outer IUnknown), so the
    // object's real reference count and interface lookup live here, and every interface's own
    // IUnknown methods forward to the outer object. Refusing aggregation silences the mic.
    class Inner final : public IUnknown {
    public:
        explicit Inner(SoundboardApo* self) : self_(self) {}
        STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
            if (!ppv) return E_POINTER;
            *ppv = nullptr;
            if (riid == __uuidof(IUnknown)) *ppv = static_cast<IUnknown*>(this);
            else if (riid == __uuidof(IAudioProcessingObject)) *ppv = static_cast<IAudioProcessingObject*>(self_);
            else if (riid == __uuidof(IAudioProcessingObjectRT)) *ppv = static_cast<IAudioProcessingObjectRT*>(self_);
            else if (riid == __uuidof(IAudioProcessingObjectConfiguration))
                *ppv = static_cast<IAudioProcessingObjectConfiguration*>(self_);
            else if (riid == __uuidof(IAudioSystemEffects)) *ppv = static_cast<IAudioSystemEffects*>(self_);
            else if (riid == __uuidof(IAudioSystemEffects2)) *ppv = static_cast<IAudioSystemEffects2*>(self_);
            else return E_NOINTERFACE;
            static_cast<IUnknown*>(*ppv)->AddRef();
            return S_OK;
        }
        STDMETHODIMP_(ULONG) AddRef() override { return ULONG(++refs_); }
        STDMETHODIMP_(ULONG) Release() override {
            LONG left = --refs_;
            if (left == 0) delete self_;
            return ULONG(left);
        }

    private:
        SoundboardApo* self_;
        std::atomic<LONG> refs_{1};
    };

    explicit SoundboardApo(IUnknown* outer)
        : CBaseAudioProcessingObject(g_regProperties), inner_(this), outer_(outer ? outer : &inner_) {
        ++g_objects;
    }

    ~SoundboardApo() {
        ReleaseRingOwnership();
        if (view_) UnmapViewOfFile(view_);
        if (mapping_) CloseHandle(mapping_);
        if (mixedFrames_ || lockCount_)
            Log(L"APO %p destroyed: locked %lu times, mixed %llu frames", this, lockCount_, mixedFrames_);
        --g_objects;
    }

    Inner& inner() { return inner_; }

    // Delegating IUnknown, shared by all of the object's interfaces.
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override { return outer_->QueryInterface(riid, ppv); }
    STDMETHODIMP_(ULONG) AddRef() override { return outer_->AddRef(); }
    STDMETHODIMP_(ULONG) Release() override { return outer_->Release(); }

    // IAudioProcessingObject
    STDMETHODIMP Initialize(UINT32 cbDataSize, BYTE* pbyData) override {
        if (m_bIsInitialized) return APOERR_ALREADY_INITIALIZED;
        if (!pbyData || cbDataSize < sizeof(APOInitBaseStruct)) return E_INVALIDARG;
        if (reinterpret_cast<APOInitBaseStruct*>(pbyData)->clsid != CLSID_SoundboardApo) return E_INVALIDARG;

        bool discoveryOnly = false;
        IPropertyStore* endpoint = nullptr;
        if (cbDataSize == sizeof(APOInitSystemEffects3)) {
            auto* init = reinterpret_cast<APOInitSystemEffects3*>(pbyData);
            discoveryOnly = init->InitializeForDiscoveryOnly;
            endpoint = init->pAPOEndpointProperties;
        } else if (cbDataSize == sizeof(APOInitSystemEffects2)) {
            auto* init = reinterpret_cast<APOInitSystemEffects2*>(pbyData);
            discoveryOnly = init->InitializeForDiscoveryOnly;
            endpoint = init->pAPOEndpointProperties;
        } else if (cbDataSize == sizeof(APOInitSystemEffects)) {
            endpoint = reinterpret_cast<APOInitSystemEffects*>(pbyData)->pAPOEndpointProperties;
        }

        // Windows sometimes creates us only to ask which formats and modes we support.
        if (!discoveryOnly) {
            wchar_t guid[64] = L"";
            if (ReadEndpointGuid(endpoint, guid, ARRAYSIZE(guid))) {
                OpenRing(guid);
            } else {
                Log(L"Initialize: no endpoint id (init struct %u bytes); pass-through", cbDataSize);
            }
        }
        m_bIsInitialized = true;
        return S_OK;
    }

    STDMETHODIMP Reset() override {
        if (ownsRing_) reader_.DropBacklog();
        return CBaseAudioProcessingObject::Reset();
    }

    // IAudioProcessingObjectConfiguration
    STDMETHODIMP LockForProcess(UINT32 nIn, APO_CONNECTION_DESCRIPTOR** ppIn, UINT32 nOut,
                                APO_CONNECTION_DESCRIPTOR** ppOut) override {
        HRESULT hr = CBaseAudioProcessingObject::LockForProcess(nIn, ppIn, nOut, ppOut);
        if (FAILED(hr)) {
            Log(L"LockForProcess: base class refused (0x%08lx)", hr);
            return hr;
        }
        UNCOMPRESSEDAUDIOFORMAT format{};
        hr = ppIn[0]->pFormat->GetUncompressedAudioFormat(&format);
        if (FAILED(hr)) {
            CBaseAudioProcessingObject::UnlockForProcess();
            return hr;
        }
        channels_ = format.dwSamplesPerFrame;
        rate_ = static_cast<uint32_t>(format.fFramesPerSecond + 0.5f);
        maxFrames_ = ppIn[0]->u32MaxFrameCount;
        ++lockCount_;
        try {
            scratch_.assign(size_t(maxFrames_) * sb::kRingChannels, 0.f);  // allocated here, never on the audio thread
        } catch (...) {
            scratch_.clear();
            maxFrames_ = 0;
        }
        if (view_ && maxFrames_ && TakeRingOwnership()) reader_.Start(rate_);
        Log(L"LockForProcess: %u Hz, %u ch, max %u frames, %s", rate_, channels_, maxFrames_,
            ownsRing_ ? L"reading the ring" : (view_ ? L"another instance reads the ring" : L"no ring: pass-through"));
        return S_OK;
    }

    STDMETHODIMP UnlockForProcess() override {
        ReleaseRingOwnership();
        Log(L"UnlockForProcess: mixed %llu frames so far", mixedFrames_);
        return CBaseAudioProcessingObject::UnlockForProcess();
    }

    // IAudioProcessingObjectRT. Runs on the real-time audio thread: no locks, no allocation, no logging.
    STDMETHODIMP_(void) APOProcess(UINT32 nIn, APO_CONNECTION_PROPERTY** ppIn, UINT32 nOut,
                                   APO_CONNECTION_PROPERTY** ppOut) override {
        if (nIn < 1 || nOut < 1) return;
        APO_CONNECTION_PROPERTY* in = ppIn[0];
        APO_CONNECTION_PROPERTY* out = ppOut[0];
        const UINT32 frames = in->u32ValidFrameCount;
        auto* src = reinterpret_cast<float*>(in->pBuffer);
        auto* dst = reinterpret_cast<float*>(out->pBuffer);
        const bool silent = in->u32BufferFlags == BUFFER_SILENT;
        const size_t bytes = size_t(frames) * channels_ * sizeof(float);

        uint32_t got = 0;
        if (ownsRing_) {
            reader_.Heartbeat(GetTickCount64());
            got = reader_.Read(scratch_.data(), frames < maxFrames_ ? frames : maxFrames_);
        }
        if (dst != src && !silent) memcpy(dst, src, bytes);
        if (got) {
            if (silent) memset(dst, 0, bytes);  // a silent buffer's contents are undefined
            sb::MixStereoInto(dst, channels_, scratch_.data(), got);
            out->u32BufferFlags = BUFFER_VALID;
            mixedFrames_ += got;
        } else {
            out->u32BufferFlags = in->u32BufferFlags;
        }
        out->u32ValidFrameCount = frames;
    }

    // IAudioSystemEffects2
    STDMETHODIMP GetEffectsList(LPGUID* ppEffectsIds, UINT* pcEffects, HANDLE) override {
        if (!ppEffectsIds || !pcEffects) return E_POINTER;
        *ppEffectsIds = nullptr;
        *pcEffects = 0;
        return S_OK;
    }

private:
    // The mic's endpoint GUID, "{552c99d7-...}", lowercased to match the app and the registry key name.
    static bool ReadEndpointGuid(IPropertyStore* store, wchar_t* out, size_t cch) {
        if (!store) return false;
        PROPVARIANT value;
        PropVariantInit(&value);
        bool ok = SUCCEEDED(store->GetValue(kEndpointGuidKey, &value)) && value.vt == VT_LPWSTR && value.pwszVal &&
                  SUCCEEDED(StringCchCopyW(out, cch, value.pwszVal));
        PropVariantClear(&value);
        if (ok) CharLowerW(out);
        return ok;
    }

    // Create (or reopen) this mic's ring. Any failure leaves us as a pass-through: the mic must keep working.
    void OpenRing(const wchar_t* endpointGuid) {
        wchar_t name[128];
        StringCchPrintfW(name, ARRAYSIZE(name), L"%s.%s", SB_RING_PREFIX, endpointGuid);
        PSECURITY_DESCRIPTOR sd = nullptr;
        // System, LocalService (audiodg) and admins: full. Interactive user (the app): read/write.
        if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(
                L"D:(A;;GA;;;SY)(A;;GA;;;LS)(A;;GA;;;BA)(A;;GRGW;;;IU)", SDDL_REVISION_1, &sd, nullptr)) {
            Log(L"OpenRing: security descriptor failed (%lu)", GetLastError());
            return;
        }
        SECURITY_ATTRIBUTES sa{sizeof(sa), sd, FALSE};
        const size_t bytes = sb::RingBytes(sb::kRingCapacity);
        mapping_ = CreateFileMappingW(INVALID_HANDLE_VALUE, &sa, PAGE_READWRITE, 0, DWORD(bytes), name);
        const DWORD err = GetLastError();
        LocalFree(sd);
        if (!mapping_) {
            Log(L"OpenRing: CreateFileMapping failed (%lu)", err);
            return;
        }
        const bool existed = err == ERROR_ALREADY_EXISTS;
        view_ = MapViewOfFile(mapping_, FILE_MAP_ALL_ACCESS, 0, 0, bytes);
        if (!view_) {
            Log(L"OpenRing: MapViewOfFile failed (%lu), existed=%d", GetLastError(), existed);
            CloseHandle(mapping_);
            mapping_ = nullptr;
            return;
        }
        if (!existed) {
            sb::InitRing(view_, sb::kRingCapacity);
        } else if (!sb::RingLooksValid(view_, sb::kRingCapacity)) {
            Log(L"OpenRing: an existing ring has the wrong layout; pass-through");
            UnmapViewOfFile(view_);
            CloseHandle(mapping_);
            view_ = nullptr;
            mapping_ = nullptr;
            return;
        }
        reader_ = sb::RingReader(view_);
        Log(L"OpenRing: %s %s", existed ? L"reusing" : L"created", name);
    }

    bool TakeRingOwnership() {
        ownsRing_ = sb::ClaimOwner(view_, GetCurrentProcessId(), instance_);
        return ownsRing_;
    }

    void ReleaseRingOwnership() {
        if (!ownsRing_) return;
        ownsRing_ = false;
        reader_.Stop();
        sb::ReleaseOwner(view_, GetCurrentProcessId(), instance_);
    }

    Inner inner_;
    IUnknown* outer_;

    HANDLE mapping_ = nullptr;
    void* view_ = nullptr;
    sb::RingReader reader_{nullptr};
    bool ownsRing_ = false;
    const uint32_t instance_ = g_nextInstance++;

    uint32_t channels_ = 0;
    uint32_t rate_ = 0;
    uint32_t maxFrames_ = 0;
    std::vector<float> scratch_;

    ULONG lockCount_ = 0;
    unsigned long long mixedFrames_ = 0;
};

// --- class factory and DLL exports ---------------------------------------------------------------

class Factory final : public IClassFactory {
public:
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        if (riid == __uuidof(IUnknown) || riid == __uuidof(IClassFactory)) {
            *ppv = static_cast<IClassFactory*>(this);
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return 2; }   // static object
    STDMETHODIMP_(ULONG) Release() override { return 1; }

    STDMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        *ppv = nullptr;
        // COM rule: an aggregated object can only be asked for its inner IUnknown at creation.
        if (outer && riid != __uuidof(IUnknown)) return CLASS_E_NOAGGREGATION;
        auto* apo = new (std::nothrow) SoundboardApo(outer);
        if (!apo) return E_OUTOFMEMORY;
        HRESULT hr = apo->inner().QueryInterface(riid, ppv);
        apo->inner().Release();  // drop the construction reference; *ppv holds one if hr succeeded
        Log(L"CreateInstance: aggregated=%d -> 0x%08lx", outer != nullptr, hr);
        return hr;
    }
    STDMETHODIMP LockServer(BOOL lock) override {
        lock ? ++g_locks : --g_locks;
        return S_OK;
    }
};

static Factory g_factory;

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}

STDAPI DllGetClassObject(REFCLSID rclsid, REFIID riid, LPVOID* ppv) {
    if (rclsid != CLSID_SoundboardApo) return CLASS_E_CLASSNOTAVAILABLE;
    return g_factory.QueryInterface(riid, ppv);
}

STDAPI DllCanUnloadNow() { return g_objects == 0 && g_locks == 0 ? S_OK : S_FALSE; }

static HRESULT SetString(HKEY root, const wchar_t* subkey, const wchar_t* name, const wchar_t* value) {
    LSTATUS s = RegSetKeyValueW(root, subkey, name, REG_SZ, value, DWORD((wcslen(value) + 1) * sizeof(wchar_t)));
    return HRESULT_FROM_WIN32(s);
}

STDAPI DllRegisterServer() {
    wchar_t path[MAX_PATH];
    if (!GetModuleFileNameW(g_module, path, MAX_PATH)) return HRESULT_FROM_WIN32(GetLastError());
    wchar_t key[128], inproc[160];
    StringCchPrintfW(key, ARRAYSIZE(key), L"Software\\Classes\\CLSID\\%s", kClsidString);
    StringCchPrintfW(inproc, ARRAYSIZE(inproc), L"%s\\InprocServer32", key);
    HRESULT hr = SetString(HKEY_LOCAL_MACHINE, key, nullptr, L"Soundboard mic");
    if (SUCCEEDED(hr)) hr = SetString(HKEY_LOCAL_MACHINE, inproc, nullptr, path);
    if (SUCCEEDED(hr)) hr = SetString(HKEY_LOCAL_MACHINE, inproc, L"ThreadingModel", L"Both");
    if (SUCCEEDED(hr)) hr = RegisterAPO(g_regProperties);
    return hr;
}

STDAPI DllUnregisterServer() {
    UnregisterAPO(CLSID_SoundboardApo);
    wchar_t key[128];
    StringCchPrintfW(key, ARRAYSIZE(key), L"Software\\Classes\\CLSID\\%s", kClsidString);
    LSTATUS s = RegDeleteTreeW(HKEY_LOCAL_MACHINE, key);
    return s == ERROR_SUCCESS || s == ERROR_FILE_NOT_FOUND ? S_OK : HRESULT_FROM_WIN32(s);
}
