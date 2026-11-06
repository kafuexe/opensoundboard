// Tiny logger: C:\ProgramData\Soundboard\apo.log plus OutputDebugString (Sysinternals DebugView).
// Never call it from APOProcess: it takes a lock and does file I/O.
#pragma once

#include <windows.h>
#include <strsafe.h>

namespace sb {

inline SRWLOCK g_logLock = SRWLOCK_INIT;

inline void Log(const wchar_t* fmt, ...) {
    wchar_t msg[768];
    va_list args;
    va_start(args, fmt);
    StringCchVPrintfW(msg, ARRAYSIZE(msg), fmt, args);
    va_end(args);

    SYSTEMTIME t;
    GetLocalTime(&t);
    wchar_t line[900];
    StringCchPrintfW(line, ARRAYSIZE(line), L"%04u-%02u-%02u %02u:%02u:%02u.%03u [%lu:%lu] %s\r\n", t.wYear, t.wMonth,
                     t.wDay, t.wHour, t.wMinute, t.wSecond, t.wMilliseconds, GetCurrentProcessId(),
                     GetCurrentThreadId(), msg);
    OutputDebugStringW(line);

    char utf8[1800];
    int len = WideCharToMultiByte(CP_UTF8, 0, line, -1, utf8, sizeof(utf8), nullptr, nullptr);
    if (len <= 1) return;

    AcquireSRWLockExclusive(&g_logLock);
    const wchar_t* path = L"C:\\ProgramData\\Soundboard\\apo.log";
    WIN32_FILE_ATTRIBUTE_DATA info;
    bool tooBig = GetFileAttributesExW(path, GetFileExInfoStandard, &info) && (info.nFileSizeHigh || info.nFileSizeLow > 1 << 20);
    HANDLE f = CreateFileW(path, tooBig ? GENERIC_WRITE : FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                           tooBig ? CREATE_ALWAYS : OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f != INVALID_HANDLE_VALUE) {
        DWORD written;
        WriteFile(f, utf8, DWORD(len - 1), &written, nullptr);
        CloseHandle(f);
    }
    ReleaseSRWLockExclusive(&g_logLock);
}

}  // namespace sb
