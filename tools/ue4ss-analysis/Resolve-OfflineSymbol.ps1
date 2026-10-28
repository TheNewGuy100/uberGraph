param(
    [Parameter(Mandatory=$true)][string]$ImagePath,
    [Parameter(Mandatory=$true)][string]$SymbolsPath,
    [Parameter(Mandatory=$true)][UInt64]$Rva
)
$ErrorActionPreference = 'Stop'
Write-Output "[$(Get-Date -Format 'dd-MM-yyyy HH:mm:ss')] Begin offline symbol lookup (no target execution or attachment)"
try {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class OfflineSdkSymbols {
    const string DbgHelp = @"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\dbghelp.dll";
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport(DbgHelp, CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SymInitializeW(IntPtr p,string path,bool invade);
    [DllImport(DbgHelp)] static extern uint SymSetOptions(uint options);
    delegate bool SymbolCallback(IntPtr process,uint action,ulong data,ulong context);
    [DllImport(DbgHelp)] static extern bool SymRegisterCallback64(IntPtr p,SymbolCallback callback,ulong context);
    [DllImport(DbgHelp, CharSet=CharSet.Unicode, SetLastError=true)] static extern ulong SymLoadModuleExW(IntPtr p,IntPtr file,string image,string module,ulong address,uint size,IntPtr data,uint flags);
    [DllImport(DbgHelp, SetLastError=true)] static extern bool SymFromAddr(IntPtr p,ulong address,out ulong displacement,IntPtr symbol);
    [DllImport(DbgHelp, SetLastError=true)] static extern bool SymGetLineFromAddr64(IntPtr p,ulong address,out uint displacement,ref Line64 line);
    [DllImport(DbgHelp)] static extern bool SymCleanup(IntPtr p);
    [StructLayout(LayoutKind.Sequential)] struct Line64 { public uint Size; public IntPtr Key; public uint LineNumber; public IntPtr FileName; public ulong Address; }
    public static string Resolve(string image,string symbols,ulong rva) {
        // DbgHelp permits a unique non-process handle for offline symbol-only sessions.
        // Do not let a live module at the same preferred base override the input image.
        IntPtr p=new IntPtr(0x55453453);
        // Local-only symbol path supplied by caller; exact symbols, lines, fail-critical-errors, no prompts.
        SymSetOptions(0x10|0x200|0x400|0x80000|0x80000000);
        if(!SymInitializeW(p,symbols,false)) throw new Exception("SymInitialize: "+Marshal.GetLastWin32Error());
        SymbolCallback callback=delegate(IntPtr process,uint action,ulong data,ulong context) {
            if(action==0x10000000) Console.Write(Marshal.PtrToStringAnsi(new IntPtr(unchecked((long)data))));
            return false;
        };
        SymRegisterCallback64(p,callback,0);
        try {
            ulong b=SymLoadModuleExW(p,IntPtr.Zero,image,"UE4SS",0x180000000,0,IntPtr.Zero,0);
            if(b==0) throw new Exception("SymLoadModule: "+Marshal.GetLastWin32Error());
            IntPtr s=Marshal.AllocHGlobal(88+2048);
            try {
                for(int i=0;i<88+2048;i++) Marshal.WriteByte(s,i,0);
                Marshal.WriteInt32(s,0,88); Marshal.WriteInt32(s,80,2048);
                ulong d;
                if(!SymFromAddr(p,b+rva,out d,s)) throw new Exception("SymFromAddr: "+Marshal.GetLastWin32Error());
                string result="Symbol="+Marshal.PtrToStringAnsi(IntPtr.Add(s,84))+" +0x"+d.ToString("X");
                Line64 line=new Line64(); line.Size=(uint)Marshal.SizeOf(typeof(Line64)); uint ld;
                if(SymGetLineFromAddr64(p,b+rva,out ld,ref line)) result+="\nSource="+Marshal.PtrToStringAnsi(line.FileName)+":"+line.LineNumber+" +0x"+ld.ToString("X");
                else result+="\nSourceLineUnavailable="+Marshal.GetLastWin32Error();
                return result;
            } finally { Marshal.FreeHGlobal(s); }
        } finally { SymCleanup(p); GC.KeepAlive(callback); }
    }
}
'@
    [OfflineSdkSymbols]::Resolve($ImagePath, $SymbolsPath, $Rva)
} finally {
    Write-Output "[$(Get-Date -Format 'dd-MM-yyyy HH:mm:ss')] End offline symbol lookup"
}
