// SoundboardCapture.exe: captures one app's audio (Windows 10 2004+ "process loopback") so the
// Soundboard app can stream it into the mic.
//
//   SoundboardCapture list           apps with audio sessions, one per line, UTF-8, tab-separated:
//                                    <pid>\t<1 if playing now, else 0>\t<exe name>\t<friendly name>
//   SoundboardCapture capture <pid>  that app's audio (and its child processes') as raw 48 kHz stereo
//                                    float32 on stdout, until the app exits or stdout is closed.
//
// Exit codes: 0 done, 2 bad arguments, 3 the app exited, 4 capture couldn't start (old Windows,
// or the process is gone), 5 stdout closed.

#include <windows.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <audiopolicy.h>
#include <fcntl.h>
#include <io.h>
#include <mmdeviceapi.h>
#include <tlhelp32.h>

#include <cstdio>
#include <cwchar>
#include <map>
#include <string>
#include <vector>

namespace {

std::wstring ExePath(DWORD pid) {
    std::wstring out;
    if (HANDLE p = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid)) {
        wchar_t buf[MAX_PATH * 2];
        DWORD n = ARRAYSIZE(buf);
        if (QueryFullProcessImageNameW(p, 0, buf, &n)) out.assign(buf, n);
        CloseHandle(p);
    }
    return out;
}

std::wstring BaseName(const std::wstring& path) {
    size_t slash = path.find_last_of(L"\\/");
    return slash == std::wstring::npos ? path : path.substr(slash + 1);
}

// "Spotify", "Google Chrome": the exe's FileDescription, else its file name without ".exe".
std::wstring FriendlyName(const std::wstring& path) {
    DWORD ignored = 0, size = GetFileVersionInfoSizeW(path.c_str(), &ignored);
    if (size) {
        std::vector<BYTE> data(size);
        struct Lang { WORD lang, codepage; }* langs = nullptr;
        UINT len = 0;
        if (GetFileVersionInfoW(path.c_str(), 0, size, data.data()) &&
            VerQueryValueW(data.data(), L"\\VarFileInfo\\Translation", reinterpret_cast<void**>(&langs), &len) && len) {
            wchar_t key[64];
            swprintf_s(key, L"\\StringFileInfo\\%04x%04x\\FileDescription", langs[0].lang, langs[0].codepage);
            wchar_t* text = nullptr;
            if (VerQueryValueW(data.data(), key, reinterpret_cast<void**>(&text), &len) && len > 1 && text[0])
                return text;
        }
    }
    std::wstring name = BaseName(path);
    if (name.size() > 4 && _wcsicmp(name.c_str() + name.size() - 4, L".exe") == 0) name.resize(name.size() - 4);
    return name;
}

// Browsers and Spotify play audio from child processes. Report the top process with the same
// exe, so capturing "its process tree" gets every tab and survives a child restarting.
DWORD RootOfSameApp(DWORD pid, const std::map<DWORD, DWORD>& parents) {
    const std::wstring exe = BaseName(ExePath(pid));
    for (int guard = 0; guard < 32; ++guard) {
        auto it = parents.find(pid);
        if (it == parents.end() || it->second == 0) break;
        if (_wcsicmp(BaseName(ExePath(it->second)).c_str(), exe.c_str()) != 0) break;
        pid = it->second;
    }
    return pid;
}

void PrintUtf8(const std::wstring& text) {
    int n = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), -1, nullptr, 0, nullptr, nullptr);
    std::string out(n > 0 ? n - 1 : 0, '\0');
    if (n > 1) WideCharToMultiByte(CP_UTF8, 0, text.c_str(), -1, out.data(), n, nullptr, nullptr);
    fwrite(out.data(), 1, out.size(), stdout);
}

int List() {
    std::map<DWORD, DWORD> parents;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32W pe{sizeof(pe)};
    if (snap != INVALID_HANDLE_VALUE && Process32FirstW(snap, &pe)) {
        do parents[pe.th32ProcessID] = pe.th32ParentProcessID; while (Process32NextW(snap, &pe));
    }
    if (snap != INVALID_HANDLE_VALUE) CloseHandle(snap);

    std::map<DWORD, bool> apps;  // root pid -> playing now
    IMMDeviceEnumerator* devices = nullptr;
    if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&devices)))) return 4;
    IMMDeviceCollection* outputs = nullptr;
    UINT count = 0;
    if (SUCCEEDED(devices->EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE, &outputs))) outputs->GetCount(&count);
    for (UINT i = 0; i < count; ++i) {
        IMMDevice* device = nullptr;
        IAudioSessionManager2* manager = nullptr;
        IAudioSessionEnumerator* sessions = nullptr;
        int n = 0;
        if (SUCCEEDED(outputs->Item(i, &device)) &&
            SUCCEEDED(device->Activate(__uuidof(IAudioSessionManager2), CLSCTX_ALL, nullptr, reinterpret_cast<void**>(&manager))) &&
            SUCCEEDED(manager->GetSessionEnumerator(&sessions)) && SUCCEEDED(sessions->GetCount(&n))) {
            for (int s = 0; s < n; ++s) {
                IAudioSessionControl* control = nullptr;
                IAudioSessionControl2* control2 = nullptr;
                DWORD pid = 0;
                AudioSessionState state = AudioSessionStateInactive;
                if (SUCCEEDED(sessions->GetSession(s, &control)) &&
                    SUCCEEDED(control->QueryInterface(IID_PPV_ARGS(&control2))) &&
                    control2->IsSystemSoundsSession() != S_OK && SUCCEEDED(control2->GetProcessId(&pid)) && pid &&
                    SUCCEEDED(control2->GetState(&state)) && state != AudioSessionStateExpired) {
                    DWORD root = RootOfSameApp(pid, parents);
                    apps[root] = apps[root] || state == AudioSessionStateActive;
                }
                if (control2) control2->Release();
                if (control) control->Release();
            }
        }
        if (sessions) sessions->Release();
        if (manager) manager->Release();
        if (device) device->Release();
    }
    if (outputs) outputs->Release();
    devices->Release();

    for (const auto& [pid, playing] : apps) {
        std::wstring path = ExePath(pid);
        if (path.empty()) continue;  // gone, or we can't look at it
        wchar_t head[32];
        swprintf_s(head, L"%lu\t%d\t", pid, playing ? 1 : 0);
        PrintUtf8(head + BaseName(path) + L"\t" + FriendlyName(path) + L"\n");
    }
    return 0;
}

// Hands the activated IAudioClient back from ActivateAudioInterfaceAsync's worker thread.
class Activation final : public IActivateAudioInterfaceCompletionHandler, public IAgileObject {
public:
    Activation() : done_(CreateEventW(nullptr, TRUE, FALSE, nullptr)) {}
    ~Activation() { CloseHandle(done_); }
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (riid == __uuidof(IUnknown) || riid == __uuidof(IActivateAudioInterfaceCompletionHandler))
            *ppv = static_cast<IActivateAudioInterfaceCompletionHandler*>(this);
        else if (riid == __uuidof(IAgileObject))
            *ppv = static_cast<IAgileObject*>(this);
        else
            return *ppv = nullptr, E_NOINTERFACE;
        AddRef();
        return S_OK;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    STDMETHODIMP_(ULONG) Release() override { return InterlockedDecrement(&refs_); }  // lives on main's stack
    STDMETHODIMP ActivateCompleted(IActivateAudioInterfaceAsyncOperation* op) override {
        IUnknown* unknown = nullptr;
        HRESULT activated = E_FAIL;
        hr = op->GetActivateResult(&activated, &unknown);
        if (SUCCEEDED(hr)) hr = activated;
        if (SUCCEEDED(hr) && unknown) hr = unknown->QueryInterface(IID_PPV_ARGS(&client));
        if (unknown) unknown->Release();
        SetEvent(done_);
        return S_OK;
    }
    bool Wait(DWORD ms) { return WaitForSingleObject(done_, ms) == WAIT_OBJECT_0; }

    HRESULT hr = E_PENDING;
    IAudioClient* client = nullptr;

private:
    HANDLE done_;
    LONG refs_ = 1;
};

int Capture(DWORD pid) {
    HANDLE target = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!target) {
        fwprintf(stderr, L"process %lu isn't running\n", pid);
        return 4;
    }
    AUDIOCLIENT_ACTIVATION_PARAMS params{};
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    params.ProcessLoopbackParams.TargetProcessId = pid;
    params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
    PROPVARIANT activateParams{};
    activateParams.vt = VT_BLOB;
    activateParams.blob.cbSize = sizeof(params);
    activateParams.blob.pBlobData = reinterpret_cast<BYTE*>(&params);

    Activation activation;
    IActivateAudioInterfaceAsyncOperation* op = nullptr;
    HRESULT hr = ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, __uuidof(IAudioClient),
                                             &activateParams, &activation, &op);
    if (FAILED(hr) || !activation.Wait(10000) || FAILED(activation.hr)) {
        fwprintf(stderr, L"couldn't start capturing (0x%08lx / 0x%08lx); needs Windows 10 2004 or newer\n",
                 hr, activation.hr);
        if (op) op->Release();
        return 4;
    }
    op->Release();
    IAudioClient* client = activation.client;

    WAVEFORMATEX format{};
    format.wFormatTag = WAVE_FORMAT_IEEE_FLOAT;
    format.nChannels = 2;
    format.nSamplesPerSec = 48000;
    format.wBitsPerSample = 32;
    format.nBlockAlign = format.nChannels * format.wBitsPerSample / 8;
    format.nAvgBytesPerSec = format.nSamplesPerSec * format.nBlockAlign;
    hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED,
                            AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK |
                                AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
                            200000 /* 20 ms */, 0, &format, nullptr);
    HANDLE ready = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    IAudioCaptureClient* capture = nullptr;
    if (SUCCEEDED(hr)) hr = client->SetEventHandle(ready);
    if (SUCCEEDED(hr)) hr = client->GetService(IID_PPV_ARGS(&capture));
    if (SUCCEEDED(hr)) hr = client->Start();
    if (FAILED(hr)) {
        fwprintf(stderr, L"couldn't start capturing (0x%08lx)\n", hr);
        return 4;
    }

    int exitCode = 0;
    std::vector<float> silence;
    for (;;) {
        if (WaitForSingleObject(target, 0) == WAIT_OBJECT_0) {
            exitCode = 3;
            break;
        }
        WaitForSingleObject(ready, 200);
        UINT32 packet = 0;
        while (SUCCEEDED(capture->GetNextPacketSize(&packet)) && packet) {
            BYTE* data = nullptr;
            UINT32 frames = 0;
            DWORD flags = 0;
            if (FAILED(capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr))) break;
            const void* bytes = data;
            if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {
                silence.assign(size_t(frames) * 2, 0.f);
                bytes = silence.data();
            }
            const size_t written = fwrite(bytes, format.nBlockAlign, frames, stdout);
            capture->ReleaseBuffer(frames);
            if (written != frames || fflush(stdout) != 0) {
                exitCode = 5;  // Soundboard stopped reading
                goto done;
            }
        }
    }
done:
    client->Stop();
    capture->Release();
    client->Release();
    CloseHandle(ready);
    CloseHandle(target);
    return exitCode;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    _setmode(_fileno(stdout), _O_BINARY);
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 4;
    int code = 2;
    if (argc == 2 && wcscmp(argv[1], L"list") == 0) {
        code = List();
    } else if (argc == 3 && wcscmp(argv[1], L"capture") == 0) {
        DWORD pid = wcstoul(argv[2], nullptr, 10);
        code = pid ? Capture(pid) : 2;
    } else {
        fwprintf(stderr, L"usage: SoundboardCapture list | capture <pid>\n");
    }
    CoUninitialize();
    return code;
}
